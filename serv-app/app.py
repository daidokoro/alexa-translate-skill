from boto3 import client
from flask import Flask, render_template
from flask_ask import Ask, statement
from xml.sax.saxutils import escape
import subprocess


# Define Classes
class SkillRequest:
    '''
    SkillRequest Class handles the interaction between AWS S3 & Polly and the Google Translate Binary.
    '''

    polly = client('polly', region_name="eu-west-1")
    s3 = client('s3')
    bucket = 'alexa-translate'

    def __init__(self, text):
        self.text = text

        # Run
        self.translate()
        self.get_stream()
        self.save_mp3_to_s3()
        self.get_url()

    def translate(self):
        # Translate text using Go Binary & Google Translate API
        cmd = ['translate', '-l', 'es', '-t', self.text]
        self.translation, self.err = subprocess.Popen(cmd, stdout=subprocess.PIPE).communicate()


    def get_stream(self):
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


    def get_url(self):
        # Gets a presigned url of mp3 via S3
        self.url = escape(SkillRequest.s3.generate_presigned_url(
            ExpiresIn=300,
            ClientMethod='get_object',
            Params={
                'Bucket': SkillRequest.bucket,
                'Key': self.key
            }
        )).encode('utf-8')



# Define flask API
app = Flask(__name__)
ask = Ask(app, '/')

@ask.intent('TranslateIntent')
def translate(text):

    print("Translating --> %s" % text)

    # Getting translation and mp3 url
    s = SkillRequest(text)

    print("Translation --> %s\nMP3 URL --> %s" % (s.translation, s.url))

    resp = render_template(
        'translate_response',
        text=text,
        translation_url=s.url
    )
    print(resp)



    return statement(resp)#.simple_card(text, s.translation,)

if __name__ == '__main__':
    app.run()
