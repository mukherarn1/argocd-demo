from constructs import Construct
import aws_cdk as cdk
from aws_cdk import (
    pipelines,
    Stage,
    aws_codepipeline as codepipeline,
    aws_codepipeline_actions as codepipeline_actions,
    aws_lambda as lambda_,
    aws_codebuild as codebuild,
    aws_eks as eks,
    aws_iam as iam,
    CfnOutput
    
)
import os
import json
from constructs import Construct
import constructs
from aws_cdk import Stack
from constructs import Construct
from aws_cdk.pipelines import CodePipeline, CodePipelineSource, ShellStep
from aws_cdk.aws_codecommit import Repository
from aws_cdk.aws_codepipeline_actions import CodeCommitTrigger
from aws_cdk import Stack
import jsii
from aws_cdk import aws_codepipeline as codepipeline
from aws_cdk import aws_codepipeline_actions as cpactions
from stacks.buildStack import buildStack
from stacks.EksClusterStack import EksClusterStack
from stacks.CodeBuildEksStack import CodeBuildEksStack

with open('var.config.json') as f:
    _var = json.load(f)
    
def add_pipeline_stages(self, pipeline):
    build_stage = buildStage(
        self,
        "buildStage",
        env={
            "account": _var["Account"],
            "region": _var["Region"],
        },
    )

    pipeline.add_stage(build_stage,
        post=[
            pipelines.ShellStep(
                "TriggerAndMonitorCodeBuild",
                commands=[
                    f"""
                    BUILD_ID=$(aws codebuild start-build --project-name codebuildproject-{_var['app_name']}-argocd --region {_var['Region']} --query 'build.id' --output text)
                    echo "Started build with ID: $BUILD_ID"
                    
                    while true; do
                        STATUS=$(aws codebuild batch-get-builds --ids $BUILD_ID --query 'builds[0].buildStatus' --output text)
                        echo "Current status: $STATUS"
                        if [ "$STATUS" = "SUCCEEDED" ]; then
                            echo "Build succeeded"
                            exit 0
                        elif [ "$STATUS" = "FAILED" ] || [ "$STATUS" = "STOPPED" ]; then
                            echo "Build failed or stopped"
                            exit 1
                        fi
                        sleep 30
                    done
                    """
                ],
                env={
                    "AWS_DEFAULT_REGION": _var['Region']
                }
            )
        ]
    )

    eks_stage = EksClusterStage(
        self,
        "EksClusterStage",
        env={
            "account": _var["Account"],
            "region": _var["Region"],
        },
    )

    pipeline.add_stage(eks_stage)

    codebuild_stage = CodeBuildStage(
        self,
        "CodeBuildStage",
        env={
            "account": _var["Account"],
            "region": _var["Region"],
        },
    )

    pipeline.add_stage(codebuild_stage,
        post=[
            pipelines.ShellStep(
                "TriggerAndMonitorCodeBuild1",
            commands=[
                f"""
                BUILD_ID=$(aws codebuild start-build --project-name EksInteraction-eksargocd --region {_var['Region']} --query 'build.id' --output text)
                echo "Started build with ID: $BUILD_ID"
                
                while true; do
                    STATUS=$(aws codebuild batch-get-builds --ids $BUILD_ID --query 'builds[0].buildStatus' --output text)
                    echo "Current status: $STATUS"
                    if [ "$STATUS" = "SUCCEEDED" ]; then
                        echo "Build succeeded"
                        exit 0
                    elif [ "$STATUS" = "FAILED" ] || [ "$STATUS" = "STOPPED" ]; then
                        echo "Build failed or stopped"
                        exit 1
                    fi
                    sleep 30
                done
                """
            ],
            env={
                "AWS_DEFAULT_REGION": _var['Region']
            }
        )])


class buildStage(cdk.Stage):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.build_stack = buildStack(self, 'build')

class EksClusterStage(Stage):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.eks_stack = EksClusterStack(self, 'EksCluster')


class CodeBuildStage(Stage):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.codebuild_stack = CodeBuildEksStack(self, 'CodeBuildEks')