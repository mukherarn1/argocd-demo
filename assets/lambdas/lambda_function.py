import boto3
import json
import urllib3

# Custom cfnresponse implementation
def cfnresponse_send(event, context, responseStatus, responseData, physicalResourceId=None, noEcho=False):
    responseUrl = event.get('ResponseURL')
    
    if responseUrl:
        responseBody = {
            'Status': responseStatus,
            'Reason': 'See the details in CloudWatch Log Stream: ' + context.log_stream_name,
            'PhysicalResourceId': physicalResourceId or context.log_stream_name,
            'StackId': event.get('StackId'),
            'RequestId': event.get('RequestId'),
            'LogicalResourceId': event.get('LogicalResourceId'),
            'NoEcho': noEcho,
            'Data': responseData
        }
        
        json_responseBody = json.dumps(responseBody)
        
        headers = {
            'content-type': '',
            'content-length': str(len(json_responseBody))
        }
        
        try:
            http = urllib3.PoolManager()
            response = http.request('PUT', responseUrl, headers=headers, body=json_responseBody)
            print("CFN response status code:", response.status)
        except Exception as e:
            print("Failed to send CFN response:", str(e))

def lambda_handler(event, context):
    print("Received event:", json.dumps(event, indent=2))
    
    iam_client = boto3.client('iam')
    secrets_manager = boto3.client('secretsmanager')
    
    try:
        user_name = event['ResourceProperties']['UserName']
        secret_arn = event['ResourceProperties']['SecretArn']
        
        if event['RequestType'] in ['Create', 'Update']:
            # Create service-specific credential
            response = iam_client.create_service_specific_credential(
                UserName=user_name,
                ServiceName='codecommit.amazonaws.com'
            )
            
            credential = response['ServiceSpecificCredential']
            
            # Store credentials in Secrets Manager
            secrets_manager.put_secret_value(
                SecretId=secret_arn,
                SecretString=json.dumps({
                    'username': credential['ServiceUserName'],
                    'password': credential['ServicePassword']
                })
            )
            
            result = {
                'ServiceUserName': credential['ServiceUserName'],
                'ServiceSpecificCredentialId': credential['ServiceSpecificCredentialId']
            }
            
            print("Credential created:", json.dumps(result, indent=2))
            
            if 'ResponseURL' in event:
                cfnresponse_send(event, context, "SUCCESS", result, physicalResourceId=credential['ServiceUserName'])
            
            return result
        
        elif event['RequestType'] == 'Delete':
            if 'PhysicalResourceId' in event:
                credential_id = event['PhysicalResourceId']
                
                # Delete service-specific credential
                iam_client.delete_service_specific_credential(
                    UserName=user_name,
                    ServiceSpecificCredentialId=credential_id
                )
                
                print(f"Deleted credential: {credential_id}")
            
            if 'ResponseURL' in event:
                cfnresponse_send(event, context, "SUCCESS", {})
            
            return {"Status": "Deleted"}
    
    except Exception as e:
        error_message = str(e)
        print(f"Error: {error_message}")
        
        if 'ResponseURL' in event:
            cfnresponse_send(event, context, "FAILED", {"Error": error_message})
        
        raise e