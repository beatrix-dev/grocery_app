#!/usr/bin/env python3
import os

import aws_cdk as cdk

from grocery_app.grocery_app_stack import GroceryAppStack


app = cdk.App()

GroceryAppStack(
    app,
    "GroceryAppStack",
    frontend_origin=app.node.try_get_context("frontend_origin")
    or os.getenv("FRONTEND_ORIGIN", "*"),
)

app.synth()
