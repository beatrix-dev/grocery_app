from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as integrations,
    aws_logs as logs,
    aws_s3 as s3,
)
from constructs import Construct


class GroceryAppStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        frontend_origin: str = "*",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        receipts_bucket = s3.Bucket(
            self,
            "ReceiptsBucket",
            versioned=False,
            auto_delete_objects=True,
            removal_policy=RemovalPolicy.DESTROY,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
        )

        price_table = dynamodb.Table(
            self,
            "PriceTable",
            partition_key=dynamodb.Attribute(
                name="PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            point_in_time_recovery=True,
        )

        common_environment = {
            "TABLE_NAME": price_table.table_name,
            "BUCKET_NAME": receipts_bucket.bucket_name,
            "ALLOWED_ORIGIN": frontend_origin,
            "DEFAULT_USER_ID": "demo-user",
        }

        api_lambda = _lambda.Function(
            self,
            "GroceryApiHandler",
            runtime=_lambda.Runtime.PYTHON_3_11,
            code=_lambda.Code.from_asset("grocery_app/lambda/api"),
            handler="handler.handler",
            timeout=Duration.seconds(15),
            memory_size=256,
            log_retention=logs.RetentionDays.ONE_WEEK,
            environment=common_environment,
        )

        ocr_lambda = _lambda.Function(
            self,
            "ReceiptOcrHandler",
            runtime=_lambda.Runtime.PYTHON_3_11,
            code=_lambda.Code.from_asset("grocery_app/lambda/ocr_scan"),
            handler="handler.handler",
            timeout=Duration.seconds(30),
            memory_size=512,
            log_retention=logs.RetentionDays.ONE_WEEK,
            environment=common_environment,
        )

        receipts_bucket.grant_read_write(api_lambda)
        receipts_bucket.grant_read_write(ocr_lambda)
        price_table.grant_read_write_data(api_lambda)
        price_table.grant_read_write_data(ocr_lambda)

        ocr_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["textract:AnalyzeExpense"],
                resources=["*"],
            )
        )

        http_api = apigwv2.HttpApi(
            self,
            "GroceryHttpApi",
            api_name="grocery-price-tracker-api",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_headers=["content-type"],
                allow_methods=[
                    apigwv2.CorsHttpMethod.GET,
                    apigwv2.CorsHttpMethod.POST,
                    apigwv2.CorsHttpMethod.OPTIONS,
                ],
                allow_origins=[frontend_origin] if frontend_origin != "*" else ["*"],
                max_age=Duration.hours(1),
            ),
        )

        api_integration = integrations.HttpLambdaIntegration(
            "GroceryApiIntegration", api_lambda
        )
        ocr_integration = integrations.HttpLambdaIntegration(
            "ReceiptOcrIntegration", ocr_lambda
        )

        http_api.add_routes(
            path="/entries",
            methods=[apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
            integration=api_integration,
        )
        http_api.add_routes(
            path="/entries/bulk",
            methods=[apigwv2.HttpMethod.POST],
            integration=api_integration,
        )
        http_api.add_routes(
            path="/summary",
            methods=[apigwv2.HttpMethod.GET],
            integration=api_integration,
        )
        http_api.add_routes(
            path="/receipts/text",
            methods=[apigwv2.HttpMethod.POST],
            integration=api_integration,
        )
        http_api.add_routes(
            path="/upload-url",
            methods=[apigwv2.HttpMethod.POST],
            integration=api_integration,
        )
        http_api.add_routes(
            path="/receipts/scan",
            methods=[apigwv2.HttpMethod.POST],
            integration=ocr_integration,
        )

        CfnOutput(self, "ApiUrl", value=http_api.url or "")
        CfnOutput(self, "BucketName", value=receipts_bucket.bucket_name)
        CfnOutput(self, "TableName", value=price_table.table_name)
