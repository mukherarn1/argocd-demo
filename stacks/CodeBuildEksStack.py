from aws_cdk import (
    Stack,
    aws_iam as iam,
    aws_codebuild as codebuild,
    aws_eks as eks,
    CfnOutput,
    aws_secretsmanager as secretsmanager,
    SecretValue,
    CustomResource,
    custom_resources as cr,
    aws_logs as logs,
    Duration,
    aws_lambda as lambda_
)
from constructs import Construct
from os import path
import os
import json

with open(os.path.dirname(__file__) + '/../var.config.json') as f:
    _var = json.load(f)

class CodeBuildEksStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create an EKS cluster object (you might need to import it from another stack)
        eks_cluster = eks.Cluster.from_cluster_attributes(
            self, "ImportedCluster",
            cluster_name=_var["clusterName"],
            kubectl_role_arn=f'arn:aws:iam::{_var["Account"]}:role/{_var["clusterRoleName"]}'
        )
        
        # Create the masters role
        masters_role = iam.Role.from_role_arn(
            self, "ImportedMastersRole",
            role_arn=f'arn:aws:iam::{_var["Account"]}:role/{_var["clusterRoleName"]}'
        )

        # Create IAM role for CodeBuild
        self.codebuild_role = iam.Role(
            self, "CodeBuildEksRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com")
        )

        # Allow CodeBuild role to assume the masters role
        masters_role.grant_assume_role(self.codebuild_role)

        # Add EKS permissions to CodeBuild role
        self.codebuild_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "eks:DescribeCluster",
                "eks:ListClusters",
                "eks:AccessKubernetesApi",
                "ec2:DescribeInstances",
                "elasticloadbalancing:DescribeLoadBalancers",
                "elasticloadbalancing:DescribeInstanceHealth"
            ],
            resources=["*"]
        ))

        # Allow CodeBuild role to assume the masters role
        self.codebuild_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["sts:AssumeRole"],
            resources=[masters_role.role_arn]
        ))

        # Add CodeCommit permissions to CodeBuild role
        self.codebuild_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "codecommit:GetBranch",
                "codecommit:GetCommit",
                "codecommit:GetRepository",
                "codecommit:GitPull",
                "codecommit:GetAuthorizationToken",
                "codecommit:ListBranches",
                "codecommit:ListRepositories"
            ],
            resources=["*"]
        ))

        # Create IAM User for CodeCommit
        codecommit_user = iam.User(self, "CodeCommitUser",
            user_name="codecommit-user",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AWSCodeCommitPowerUser")
            ]
        )

        # Create a Secret to store Git credentials
        git_creds_secret = secretsmanager.Secret(self, "GitCredentialsSecret",
            secret_name="codecommit/git-credentials",
            description="Git credentials for CodeCommit"
        )

        # Grant CodeBuild role permission to read the secret
        git_creds_secret.grant_read(self.codebuild_role)

        # Create Lambda function to generate Git credentials and store in Secrets Manager
        git_creds_lambda = self.create_git_credentials_lambda(codecommit_user.user_name, git_creds_secret.secret_arn)

        # Create a Custom Resource to trigger the Lambda function
        git_creds_resource = CustomResource(
            self, "GitCredentialsResource",
            service_token=git_creds_lambda.function_arn,
            properties={
                "UserName": codecommit_user.user_name,
                "SecretArn": git_creds_secret.secret_arn
            }
        )

        # Create CodeBuild project
        self.codebuild_project = codebuild.Project(
            self, "EksInteractionProject",
            project_name="EksInteraction-eksargocd",
            description="Project to interact with EKS cluster",
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_5_0,
                privileged=True
            ),
            environment_variables={
                "CLUSTER_NAME": codebuild.BuildEnvironmentVariable(value=eks_cluster.cluster_name),
                "REGION": codebuild.BuildEnvironmentVariable(value=self.region),
                "KUBECTL_ROLE_ARN": codebuild.BuildEnvironmentVariable(value=masters_role.role_arn),
                "GIT_CREDS_SECRET_NAME": codebuild.BuildEnvironmentVariable(value=git_creds_secret.secret_name),
                "REPO_NAME": codebuild.BuildEnvironmentVariable(value=_var["SolutionRepoName"])
            },
            build_spec=self.create_build_spec(),
            role=self.codebuild_role
        )

        # Outputs
        CfnOutput(self, "CodeBuildProjectName", value=self.codebuild_project.project_name)
        CfnOutput(self, "CodeBuildRoleArn", value=self.codebuild_role.role_arn)

    def create_git_credentials_lambda(self, user_name, secret_arn):
        # Create IAM role for Lambda
        lambda_role = iam.Role(
            self, "GitCredentialsLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
            ]
        )

        # Add necessary permissions for Lambda
        lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "iam:CreateServiceSpecificCredential",
                "iam:DeleteServiceSpecificCredential",
                "secretsmanager:PutSecretValue"
            ],
            resources=[
                f"arn:aws:iam::*:user/{user_name}",
                secret_arn
            ]
        ))

        # Create Lambda function
        return lambda_.Function(
            self, "GitCredentialsLambda",
            function_name="iam_lambda_argocd",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="lambda_function.lambda_handler",
            code=lambda_.Code.from_asset(
                path.join(path.dirname(__file__), "..", "assets", "lambdas")
            ),
            role=lambda_role,
            timeout=Duration.minutes(5)
        )

    def create_build_spec(self):
        return codebuild.BuildSpec.from_object({
            "version": "0.2",
            "phases": {
                "install": {
                    "runtime-versions": {
                        "python": "3.9"
                    },
                    "commands": [
                        "curl -LO https://storage.googleapis.com/kubernetes-release/release/$(curl -s https://storage.googleapis.com/kubernetes-release/release/stable.txt)/bin/linux/amd64/kubectl",
                        "chmod +x ./kubectl",
                        "mv ./kubectl /usr/local/bin/kubectl",
                        "curl -LO https://github.com/weaveworks/eksctl/releases/latest/download/eksctl_$(uname -s)_amd64.tar.gz",
                        "tar -xzf eksctl_$(uname -s)_amd64.tar.gz -C /tmp && rm eksctl_$(uname -s)_amd64.tar.gz",
                        "mv /tmp/eksctl /usr/local/bin",
                        "curl -sSL -o /usr/local/bin/argocd https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64",
                        "chmod +x /usr/local/bin/argocd",
                        "pip install awscli --upgrade",
                        "pip install jq"
                    ]
                },
                "build": {
                    "commands": [
                        # Configure git and clone repository
                        "git config --global credential.helper '!aws codecommit credential-helper $@'",
                        "git config --global credential.UseHttpPath true",
                        "REPO_URL=https://git-codecommit.$REGION.amazonaws.com/v1/repos/$REPO_NAME",
                        "echo Repository URL: $REPO_URL",
                        "git clone $REPO_URL",
                        "cd $REPO_NAME",
                        
                        # Update kubeconfig
                        "aws eks update-kubeconfig --name $CLUSTER_NAME --region $REGION --role-arn $KUBECTL_ROLE_ARN",
                        
                        # Create namespace if it doesn't exist
                        "kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -",
                        
                        # Check if Argo CD is already installed, install if not
                        """
                        if ! kubectl get deployment argocd-server -n argocd &> /dev/null; then
                            echo "Argo CD not found. Installing..."
                            kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/v2.8.4/manifests/install.yaml
                            kubectl wait --for=condition=available --timeout=600s deployment/argocd-server -n argocd
                        else
                            echo "Argo CD is already installed."
                        fi
                        """,
                        
                        # Create LoadBalancer for Argo CD server
                        """
                        echo "Creating LoadBalancer for Argo CD server..."
                        kubectl patch svc argocd-server -n argocd -p '{"spec": {"type": "LoadBalancer"}}'
                        
                        echo "Waiting for LoadBalancer to be created..."
                        kubectl wait --for=jsonpath='{.status.loadBalancer.ingress[0].hostname}' --timeout=300s service/argocd-server -n argocd
                        
                        EXTERNAL_IP=$(kubectl get svc argocd-server -n argocd -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
                        echo "LoadBalancer created with hostname: $EXTERNAL_IP"
                        """,
                        
                        # Function to check and create LoadBalancer
                        """
                        check_and_create_lb() {
                            echo "$(date): Waiting for LoadBalancer to become active..."
                            attempt=0
                            max_attempts=10
                            until [ $attempt -ge $max_attempts ]
                            do
                                echo "$(date): Attempt $((attempt+1))/$max_attempts"
                                
                                echo "$(date): Executing kubectl command to get LB_NAME..."
                                LB_NAME=$(kubectl get svc argocd-server -n argocd -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' | awk -F- '{print $1}')
                                echo "$(date): LB_NAME = $LB_NAME"
                                
                                if [ ! -z "$LB_NAME" ]; then
                                    echo "$(date): Executing aws elb describe-load-balancers command..."
                                    DNS_NAME=$(aws elb describe-load-balancers --load-balancer-names $LB_NAME --query 'LoadBalancerDescriptions[0].DNSName' --output text)
                                    echo "$(date): DNS_NAME = $DNS_NAME"
                                    
                                    if [ ! -z "$DNS_NAME" ] && [ "$DNS_NAME" != "None" ]; then
                                        echo "$(date): LoadBalancer $LB_NAME is active with hostname: $DNS_NAME"
                                        
                                        echo "$(date): Checking instance health..."
                                        INSTANCE_STATES=$(aws elb describe-instance-health --load-balancer-name $LB_NAME --query 'InstanceStates[*].State' --output text)
                                        echo "$(date): INSTANCE_STATES = $INSTANCE_STATES"
                                        
                                        ALL_IN_SERVICE=true
                                        for STATE in $INSTANCE_STATES; do
                                            if [ "$STATE" != "InService" ]; then
                                                ALL_IN_SERVICE=false
                                                echo "$(date): Found instance not InService: $STATE"
                                                break
                                            fi
                                        done
                                        
                                        if [ "$ALL_IN_SERVICE" = true ]; then
                                            EXTERNAL_IP=$DNS_NAME
                                            echo "$(date): All instances are InService. LoadBalancer is fully active with hostname: $EXTERNAL_IP"
                                            return 0
                                        else
                                            echo "$(date): LoadBalancer $LB_NAME is active but not all instances are InService."
                                        fi
                                    else
                                        echo "$(date): DNS_NAME is empty or None"
                                    fi
                                else
                                    echo "$(date): LB_NAME is empty"
                                fi
                                
                                attempt=$((attempt+1))
                                echo "$(date): LoadBalancer not fully active yet. Waiting 20 seconds..."
                                sleep 20
                            done
                            return 1
                        }

                        # Check LoadBalancer and recreate if necessary
                        if ! check_and_create_lb; then
                            echo "LoadBalancer creation failed. Recreating Argo CD..."
                            kubectl delete namespace argocd
                            kubectl create namespace argocd
                            kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/v2.8.4/manifests/install.yaml
                            kubectl wait --for=condition=available --timeout=600s deployment/argocd-server -n argocd
                            if ! check_and_create_lb; then
                                echo "LoadBalancer creation failed again. Exiting."
                                exit 1
                            fi
                        fi

                        # Set up Argo CD server address
                        ARGOCD_SERVER=$EXTERNAL_IP
                        echo ARGOCD_SERVER=$ARGOCD_SERVER

                        # Retrieve Argo CD admin password
                        echo 'Retrieving ArgoCD admin password...'
                        ARGOCD_PASSWORD=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d)
                        echo ARGOCD_PASSWORD retrieved
                        """,
                        
                        # Log in to Argo CD with retry mechanism
                        """
                        echo 'Logging in to ArgoCD...'
                        attempt=0
                        max_attempts=5
                        until [ $attempt -ge $max_attempts ]
                        do
                            if argocd login $ARGOCD_SERVER --username admin --password $ARGOCD_PASSWORD --insecure --grpc-web; then
                                echo "Successfully logged in to ArgoCD"
                                break
                            fi
                            attempt=$((attempt+1))
                            echo "Attempt $attempt/$max_attempts: Login failed. Waiting 30 seconds before retry..."
                            sleep 10
                        done
                        if [ $attempt -ge $max_attempts ]; then
                            echo "Failed to log in to ArgoCD after multiple attempts. Exiting."
                            exit 1
                        fi
                        """,

                        "echo Retrieving CodeCommit credentials from AWS Secrets Manager...",
                        "GIT_CREDS=$(aws secretsmanager get-secret-value --secret-id $GIT_CREDS_SECRET_NAME --query SecretString --output text)",
                        "GIT_USERNAME=$(echo $GIT_CREDS | jq -r '.username')",
                        "GIT_PASSWORD=$(echo $GIT_CREDS | jq -r '.password')",
                        "echo Adding CodeCommit repository to ArgoCD...",
                        "argocd repo add $REPO_URL --username $GIT_USERNAME --password $GIT_PASSWORD --insecure",
                        "sleep 60",
                        # Read var.config.json and set environment variables
                        "echo 'Reading var.config.json...'",
                        "export $(jq -r 'to_entries | map(\"\\(.key)=\\(.value|tostring)\") | .[]' < var.config.json)",
                        
                        # Construct ECR repository URI
                        "ECR_REPO_URI=${Account}.dkr.ecr.${Region}.amazonaws.com/${ecrRepoName}",
                        "echo ECR_REPO_URI=$ECR_REPO_URI",
                        
                        # Update the deployment file with the correct image
                        "sed -i 's|${ECR_REPO_URI}:${IMAGE_TAG}|'\"$ECR_REPO_URI:$tag\"'|' manifests/guestbook-app.yaml",
                        
                        # Create ArgoCD application
                        "echo Creating ArgoCD application...",
                        "kubectl apply -n argocd -f manifests/guestbook-app.yaml",
                        "echo ArgoCD application created successfully"
                    ]
                }
            }
        })