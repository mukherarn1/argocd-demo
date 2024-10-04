from aws_cdk import (
    aws_iam as iam,
    Stack,
    aws_codebuild as codebuild,
    aws_codecommit as codecommit,
    aws_ecr as ecr,
    custom_resources as cr,
)
from constructs import Construct
import os
import json
import aws_cdk.aws_ecs as ecs
import aws_cdk.aws_ecs_patterns as ecsp
import aws_cdk as cdk
import aws_cdk.aws_ecr_assets as ecr_assets
import os.path
import aws_cdk.aws_ecs as ecs
from aws_cdk.aws_ecr_assets import DockerImageAsset
from datetime import datetime
from os import path

with open(os.path.dirname(__file__) + '/../var.config.json') as f:
    _var = json.load(f)


class buildStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        app_name =  _var["app_name"]
        image_tag_new_app_version= _var["tag"]

        # Create an AWS CodeCommit repository
        code_repo = codecommit.Repository.from_repository_name(
            self, f'argocdRepo',
            repository_name=_var["SolutionRepoName"]
        )

        # Create an Elastic Container Registry (ECR) image repository
        image_repo = ecr.Repository(self, f"ImageRepoargocd",
                                    repository_name=_var["ecrRepoName"])



        # Define the policy statement to allow pulling ima

        # CodeBuild project for new app version
        build_image_new_app_version = codebuild.Project(
            self, f"BuildImage{app_name}NewAppVersionArgocd",
            project_name=f"codebuildproject-{app_name}-argocd",
            build_spec=codebuild.BuildSpec.from_source_filename(f"{app_name}/docker_build_buildspec.yml"),
            source=codebuild.Source.code_commit(
                repository=code_repo,
                branch_or_ref=_var["Release"]
            ),
            environment=codebuild.BuildEnvironment(
                privileged=True,
                environment_variables={
                    "AWS_ACCOUNT_ID": codebuild.BuildEnvironmentVariable(value=_var["Account"] or ""),
                    "REGION": codebuild.BuildEnvironmentVariable(value=_var["Region"]),
                    "IMAGE_TAG": codebuild.BuildEnvironmentVariable(value=image_tag_new_app_version),
                    "IMAGE_REPO_NAME": codebuild.BuildEnvironmentVariable(value=image_repo.repository_name),
                    "REPOSITORY_URI": codebuild.BuildEnvironmentVariable(value=image_repo.repository_uri),
                }
            )
        )

        # Grants CodeBuild projects access to pull/push images from/to ECR repo
        image_repo.grant_pull_push(build_image_new_app_version)

        
        # IAM role for Lambda function
        build_image_new_app_version.add_to_role_policy(iam.PolicyStatement(
            actions=["codebuild:StartBuild", "codebuild:BatchGetBuilds"],
            resources=[build_image_new_app_version.project_arn]
        ))

        self.build_image_new_app_version = build_image_new_app_version

    def get_codebuild_project(self):
        return self.build_image_new_app_version
        