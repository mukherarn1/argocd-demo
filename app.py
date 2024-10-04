#!/usr/bin/env python3
import os

#!/usr/bin/env python3
import os
import json
import aws_cdk as cdk
from aws_cdk import Aspects
from constructs import Construct
from aws_cdk.pipelines import CodePipeline, CodePipelineSource, ShellStep
from aws_cdk.aws_codecommit import Repository
from aws_cdk.aws_codepipeline_actions import CodeCommitTrigger
from aws_cdk import Stack
from stacks.stage_build import add_pipeline_stages
from aws_cdk import aws_codebuild as codebuild
import jsii
from aws_cdk import (
    pipelines, aws_codecommit,
    aws_codepipeline_actions as cpactions,
    aws_codepipeline as codepipeline,
    aws_stepfunctions,
    aws_iam as iam,
    aws_codedeploy as codedeploy,
    aws_ecr as ecr,
    )
import constructs
from aws_cdk import aws_codecommit as codecommit
from aws_cdk import aws_codepipeline_actions as codepipeline_actions


# import variable file
with open('var.config.json') as f:
    _var = json.load(f)


# creating pipeline stack - WE NEED TO MAKE SURE PIPELINE STACK ALWAYS WILL BE CREATED IN app.py
class PipelineStack(cdk.Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)


        # define pipeline
        pipeline = CodePipeline(
            self,
            "Pipeline",
            pipeline_name=_var["PipelineName"],
            cross_account_keys=True,
            synth=ShellStep(
                "Synth",
                input=CodePipelineSource.code_commit(
                    repository=Repository.from_repository_name(
                        self, "SourceCodeRepo", repository_name=_var["SolutionRepoName"]
                    ),
                    branch=_var["Release"],
                    trigger=CodeCommitTrigger.NONE,
                ),
                commands=[
                    "npm install -g aws-cdk",
                    "pip install -r requirements.txt",
                    "apt-get install jq git -y -q",
                    "cdk synth",
                ],
            ),
        
        code_build_defaults = pipelines.CodeBuildOptions(
                role_policy = [
                    iam.PolicyStatement(
                        actions=["sts:AssumeRole"],
                        resources=["*"]
                    ),
                    iam.PolicyStatement(
                        actions=["codebuild:StartBuild", "codebuild:BatchGetBuilds"],
                        #resources=[f"arn:aws:codebuild:{_var['Region']}:{_var['Account']}:project/codebuildproject-{_var['app_name']}-argocd"]
                        resources=["*"]
                    )
                ]
            ),
        )
        
        add_pipeline_stages(self, pipeline)

app = cdk.App()

PipelineStack(app, f"""{_var["SolutionName"]}-Pipeline-Stack""", env={
    "account": _var["Account"],
    "region": _var["Region"]
    }
)

app.synth()
