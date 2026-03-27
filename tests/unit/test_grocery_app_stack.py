import aws_cdk as cdk
import aws_cdk.assertions as assertions

from grocery_app.grocery_app_stack import GroceryAppStack


def test_serverless_resources_created():
    app = cdk.App()
    stack = GroceryAppStack(app, "grocery-app-test", frontend_origin="*")
    template = assertions.Template.from_stack(stack)

    template.resource_count_is("AWS::DynamoDB::Table", 1)
    template.resource_count_is("AWS::Lambda::Function", 2)
    template.resource_count_is("AWS::S3::Bucket", 1)
    template.resource_count_is("AWS::ApiGatewayV2::Api", 1)
