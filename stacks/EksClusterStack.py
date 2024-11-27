from aws_cdk import (
    Stack,
    aws_eks as eks,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_codebuild as codebuild,
    CfnOutput,
)
from constructs import Construct
import os
import json

with open(os.path.dirname(__file__) + '/../var.config.json') as f:
    _var = json.load(f)


class EksClusterStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        masters_role = iam.Role(self, "EKSMastersRole",
            role_name= _var["clusterRoleName"],
            assumed_by=iam.AccountRootPrincipal()
        )

        masters_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "eks:DescribeCluster",
                "eks:ListClusters",
                "eks:AccessKubernetesApi"
            ],
            resources=["*"]
        ))
        # Create EKS Cluster
        self.cluster = eks.Cluster(
            self, "EksCluster",
            version=eks.KubernetesVersion.V1_29,
            cluster_name=_var["clusterName"],
            default_capacity=0,
            masters_role=masters_role
        )

        # Add managed node group
        node_group = self.cluster.add_nodegroup_capacity(
            "ManagedNodeGroup",
            instance_types=[ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.LARGE)],
            min_size=1,
            max_size=3,
            desired_size=2,
            ami_type=eks.NodegroupAmiType.AL2_X86_64,
        )


        # Store outputs as properties
        self.cluster_name = CfnOutput(self, "ClusterName", value=self.cluster.cluster_name)
        self.cluster_endpoint = CfnOutput(self, "ClusterEndpoint", value=self.cluster.cluster_endpoint)
        self.cluster_cert_authority_data = CfnOutput(self, "ClusterCertAuthorityData", value=self.cluster.cluster_certificate_authority_data)
