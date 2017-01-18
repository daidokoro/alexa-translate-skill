from boto3 import client
from xml.sax.saxutils import escape
import json
import subprocess
import os


# Alexa Application ID - stored in lambda env variable
app_id = os.environ.get('APPLICATION_ID')

# Define Classes
class SkillRequest:
    '''
    SkillRequest Class handles the interaction between AWS S3 & Polly and the Google Translate Binary.
    '''

    region = 'eu-west-1'
    polly = client('polly', region_name=region)
    s3 = client('s3')
    bucket = 'alexa-translate'


    def __init__(self, text):
        self.text = text

        # Run
        self._translate()
        self._get_stream()
        self.save_mp3_to_s3()
        self._get_url()

    def _translate(self):
        # Translate text using Go Binary & Google Translate API
        cmd = ['./translate', '-l', 'es', '-t', self.text]

        self.translation, self.err = subprocess.Popen(cmd, stdout=subprocess.PIPE).communicate()


    def _get_stream(self):
        # Get voice recording byte data from AWS Polly
        self.response = SkillRequest.polly.synthesize_speech(
            OutputFormat='mp3', #|'ogg_vorbis'|'pcm',
            Text=self.translation,
            VoiceId='Miguel'
        )['AudioStream'].read()

    def save_mp3(self, m):
        # Save MP3 to disk - Not used in the skill process
        with open(m, 'wb') as f:
            f.write(self.response)


    def save_mp3_to_s3(self):
        # Saves mp3 file to s3 and retreives URL
        self.key = self.text.replace(' ', '').lower() + ".mp3"
        SkillRequest.s3.put_object(
            Bucket=SkillRequest.bucket,
            Body=self.response,
            Key=self.key
        )


    def _get_url(self):
        # Gets a presigned url of mp3 via S3
        self.url = escape(SkillRequest.s3.generate_presigned_url(
            ExpiresIn=300,
            ClientMethod='get_object',
            Params={
                'Bucket': SkillRequest.bucket,
                'Key': self.key
            }
        )).encode('utf-8')


# --- AWS Lambda handler
def handler(event, context):
    # Verify app id
    print(event)

    _id = event['session']['application']['applicationId']
    if (_id != app_id):
        raise ValueError("Invalid Application ID")

    intent = event['request']['intent']['name'] # Not used (for now).
    text = event['request']['intent']['slots']['text']['value']

    # Translating
    print("Translating --> %s" % text)

    # Getting translation and mp3 url
    s = SkillRequest(text)

    print("Translation --> %s\nMP3 URL --> %s" % (s.translation, s.url))

    return {
        'version': '1.0',
        'response': {
            'outputSpeech': {
                'type': 'SSML',
                'ssml': '''<speak>%s. <audio src='%s' /></speak>''' % (s.text, s.url)
            },
            "shouldEndSession": True
        },
        'sessionAttributes': {}
    }
