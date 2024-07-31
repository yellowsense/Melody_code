from flask import Flask, request, jsonify, render_template
import uuid
import requests
import os
import logging
import azure.cognitiveservices.speech as speechsdk
from flask_cors import CORS, cross_origin
from werkzeug.utils import secure_filename
from azure.core.exceptions import ResourceExistsError
import io
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient, ContentSettings
import wave
from pydub import AudioSegment
import shutil

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.DEBUG)

CORS(app, resources={r"/*": {"origins": "*"}})
app.config['CORS_HEADERS'] = 'Content-Type'

# Function to add custom headers to every response
@app.after_request
def add_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

try:
    import customvoice
except ImportError:
    print('Please copy the folder from https://github.com/Azure-Samples/cognitive-services-speech-sdk/tree/master/samples/custom-voice/python/customvoice and keep the same folder structure as GitHub.')
    quit()

# Translator configuration
translator_endpoint = "https://api.cognitive.microsofttranslator.com"
translator_subscription_key = "fd061617ad6a42fb9c45ca3d7e11ffd1"
translator_location = "centralindia"

# Azure Blob Storage configuration
AZURE_STORAGE_CONNECTION_STRING = "DefaultEndpointsProtocol=https;AccountName=twittermelody;AccountKey=/+IBhdozqgO94QCBlVCv7fJ3AIm7X0cVfLxg7t50Xf980pExPYu+l+fpbonI5VEDhEqTtuSDGcZP+ASt5F4gmw==;EndpointSuffix=core.windows.net"
blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
container_name = "melody-audiofiles"
storage_account_name = 'twittermelody'


# Azure Blob Storage Configuration
STORAGE_ACCOUNT_NAME = 'twittermelody'
STORAGE_ACCOUNT_KEY = '/+IBhdozqgO94QCBlVCv7fJ3AIm7X0cVfLxg7t50Xf980pExPYu+l+fpbonI5VEDhEqTtuSDGcZP+ASt5F4gmw=='
CONTAINER_NAME = 'melody-audiofiles'
CONTAINER_NAME1 = 'audio-files'
TEMP_AUDIO_FOLDER = "/tmp/audio_files"  # Define the temporary audio folder


# Translator Configuration
translator_endpoint = "https://api.cognitive.microsofttranslator.com"
translator_subscription_key = "fd061617ad6a42fb9c45ca3d7e11ffd1"
translator_location = "centralindia"


# Logging
logging.basicConfig(filename="customvoice.log", format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', filemode='w')
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# Custom Voice Config
region = 'eastus'
key = 'db2c97915f82431caf66e46e46a39dbd'
config = customvoice.Config(key, region, logger)

def translate_text(text, target_language):
    path = '/translate?api-version=3.0'
    params = '&to=' + target_language
    constructed_url = translator_endpoint + path + params

    headers = {
        'Ocp-Apim-Subscription-Key': translator_subscription_key,
        'Ocp-Apim-Subscription-Region': translator_location,
        'Content-type': 'application/json',
        'X-ClientTraceId': str(uuid.uuid4())
    }

    body = [{'text': text}]
    response = requests.post(constructed_url, headers=headers, json=body)
    response.raise_for_status()
    translations = response.json()
    return translations[0]['translations'][0]['text']


def download_audio_files_from_blob(storage_account_name, storage_account_key, container_name, audio_folder_name, local_folder):
    try:
        audio_folder_path = os.path.join(local_folder, audio_folder_name)
        if os.path.exists(audio_folder_path):
            shutil.rmtree(audio_folder_path)
        os.makedirs(audio_folder_path)
        
        blob_service_client = BlobServiceClient(account_url=f"https://{storage_account_name}.blob.core.windows.net", credential=storage_account_key)
        container_client = blob_service_client.get_container_client(container_name)
        blob_list = container_client.list_blobs(name_starts_with=audio_folder_name)
        
        for blob in blob_list:
            blob_client = blob_service_client.get_blob_client(container_name, blob.name)
            local_file_path = os.path.join(audio_folder_path, os.path.basename(blob.name))
            with open(local_file_path, "wb") as download_file:
                download_file.write(blob_client.download_blob().readall())
        return audio_folder_path
    except Exception as e:
        print(f"Failed to download audio files: {str(e)}")
        raise

def create_personal_voice(config, project_id, consent_id, consent_file_path, voice_talent_name, company_name, personal_voice_id, audio_folder_name):
    try:
        # Create project
        project = customvoice.Project.create(config, project_id, customvoice.ProjectKind.PersonalVoice)
        print('Project created. Project id:', project.id)

        # Download consent file from Azure Blob Storage
        blob_service_client = BlobServiceClient(account_url=f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net", credential=STORAGE_ACCOUNT_KEY)
        blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=os.path.basename(consent_file_path))
        download_file_path = os.path.join("/tmp", os.path.basename(consent_file_path))
        with open(download_file_path, "wb") as download_file:
            download_file.write(blob_client.download_blob().readall())

        # Upload consent
        consent = customvoice.Consent.create(config, project_id, consent_id, voice_talent_name, company_name, download_file_path, 'en-us')
        if consent.status == customvoice.Status.Failed:
            print('Create consent failed. Consent id:', consent.id)
            raise Exception('Create consent failed')
        elif consent.status == customvoice.Status.Succeeded:
            print('Create consent succeeded. Consent id:', consent.id)

        # Download audio files from Azure Blob Storage
        local_audio_folder = download_audio_files_from_blob(STORAGE_ACCOUNT_NAME, STORAGE_ACCOUNT_KEY, CONTAINER_NAME, audio_folder_name, TEMP_AUDIO_FOLDER)
        print(f"Successfully downloaded audio files to {local_audio_folder}")

        # Validate audio files
        audio_files = os.listdir(local_audio_folder)
        if not audio_files:
            raise Exception(f"No audio files found in {local_audio_folder}")
        print(f"Found audio files: {audio_files}")

        # Create personal voice
        personal_voice = customvoice.PersonalVoice.create(config, project_id, personal_voice_id, consent_id, local_audio_folder)
        if personal_voice.status == customvoice.Status.Failed:
            error_message = f"Create personal voice failed. Personal voice id: {personal_voice.id}. Error details: No additional error details available."
            print(error_message)
            raise Exception(error_message)
        elif personal_voice.status == customvoice.Status.Succeeded:
            print('Create personal voice succeeded. Personal voice id:', personal_voice.id, 'Speaker profile id:', personal_voice.speaker_profile_id)
            return personal_voice.speaker_profile_id
    except Exception as e:
        print('Failed to create personal voice:', str(e))
        raise Exception('Failed to create personal voice') from e

# def speech_synthesis_to_wave_file(config, text, output_file_path, speaker_profile_id, target_language):
#     # Creates an instance of a speech config with specified subscription key and service region.
#     speech_config = speechsdk.SpeechConfig(subscription=config.key, region=config.region)
#     speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm)
#     file_config = speechsdk.audio.AudioOutputConfig(filename=output_file_path)
#     speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=file_config)

#     # Use PhoenixLatestNeural if you want word boundary event. We will support events on DragonLatestNeural in the future.
#     ssml = (
#         "<speak version='1.0' xml:lang='{language}' xmlns='http://www.w3.org/2001/10/synthesis' "
#         "xmlns:mstts='http://www.w3.org/2001/mstts'>"
#         "<voice name='DragonLatestNeural'>"
#         "<mstts:ttsembedding speakerProfileId='{speaker_id}'/>"
#         "<mstts:express-as style='Prompt'>"
#         "<lang xml:lang='{language}'>{text}</lang>"
#         "</mstts:express-as>"
#         "</voice></speak>"
#     ).format(language=target_language, speaker_id=speaker_profile_id, text=text)

#     result = speech_synthesizer.speak_ssml_async(ssml).get()
#     if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
#         # Upload synthesized audio to Azure Blob Storage
#         blob_service_client = BlobServiceClient(account_url=f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net", credential=STORAGE_ACCOUNT_KEY)
#         blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME1, blob=os.path.basename(output_file_path))
#         with open(output_file_path, "rb") as data:
#             blob_client.upload_blob(data)
#         return "Speech synthesized and uploaded to Azure Blob Storage successfully"
#     elif result.reason == speechsdk.ResultReason.Canceled:
#         cancellation_details = result.cancellation_details
#         return f"Speech synthesis canceled: {cancellation_details.reason}. Details: {cancellation_details.error_details}"


def speech_synthesis_to_wave_file(config, text, speaker_profile_id, target_language, audio_folder_name):
    try:
        unique_id = str(uuid.uuid4())[:8]  # Generate a unique ID for the file name
        output_file_name = f"{unique_id}_{audio_folder_name}.wav"
        output_file_path = f"https://twittermelody.blob.core.windows.net/audio-files/{output_file_name}"

        # Creates an instance of a speech config with specified subscription key and service region.
        speech_config = speechsdk.SpeechConfig(subscription=config.key, region=config.region)
        speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm)
        file_config = speechsdk.audio.AudioOutputConfig(filename=output_file_name)
        speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=file_config)

        # Use PhoenixLatestNeural if you want word boundary event. We will support events on DragonLatestNeural in the future.
        ssml = (
            "<speak version='1.0' xml:lang='{language}' xmlns='http://www.w3.org/2001/10/synthesis' "
            "xmlns:mstts='http://www.w3.org/2001/mstts'>"
            "<voice name='DragonLatestNeural'>"
            "<mstts:ttsembedding speakerProfileId='{speaker_id}'/>"
            "<mstts:express-as style='Prompt'>"
            "<lang xml:lang='{language}'>{text}</lang>"
            "</mstts:express-as>"
            "</voice></speak>"
        ).format(language=target_language, speaker_id=speaker_profile_id, text=text)

        result = speech_synthesizer.speak_ssml_async(ssml).get()
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            # Upload synthesized audio to Azure Blob Storage
            blob_service_client = BlobServiceClient(account_url=f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net", credential=STORAGE_ACCOUNT_KEY)
            blob_client = blob_service_client.get_blob_client(container="audio-files", blob=output_file_name)
            with open(output_file_name, "rb") as data:
                blob_client.upload_blob(data)
            return {
                "output_file_name": output_file_name,
                "output_file_path": output_file_path,
                "speaker_profile_id": speaker_profile_id,
                "synthesis_result": f"Speech synthesized and uploaded to Azure Blob Storage successfully. File path: {output_file_path}"
            }
        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            return {
                "output_file_name": output_file_name,
                "output_file_path": output_file_path,
                "speaker_profile_id": speaker_profile_id,
                "synthesis_result": f"Speech synthesis canceled: {cancellation_details.reason}. Details: {cancellation_details.error_details}"
            }
    except Exception as e:
        return {
            "error": str(e)
        }


@app.route('/process', methods=['POST'])
def api_process():
    data = request.json

    # Extract input data
    project_id = "personal-voice-project-2"
    consent_id = "personal-voice-consent-2"
    audio_folder_name = data.get('audio_folder_name', '')
    input_text = data['text']
    target_language = data['target_language']

    # Derive consent_file_path from audio_folder_name
       # Derive consent_file_path from audio_folder_name
    if audio_folder_name:
        # Assume the last part of audio_folder_name as voice_talent_name
        voice_talent_name = audio_folder_name # Take the last part
        company_name = "Yellowsense"  # Assuming company name is constant or can be derived similarly
        consent_file_path = f"https://twittermelody.blob.core.windows.net/melody-audiofiles/VoiceTalentVerbalStatement_{voice_talent_name}.wav"
    else:
        return jsonify({"error": "audio_folder_name is required."}), 400

    try:
        print("Starting personal voice creation process...")

        # Step 1: create personal voice
        personal_voice_id = "personal-voice-2"  # Assuming constant or derived similarly
        speaker_profile_id = create_personal_voice(config, project_id, consent_id, consent_file_path, voice_talent_name, company_name, personal_voice_id, audio_folder_name)

        print("Personal voice created with speaker profile ID:", speaker_profile_id)

        # Step 2: translate text
        translated_text = translate_text(input_text, target_language)

        print("Translated text:", translated_text)

        # Step 3: synthesis wave
        synthesis_result = speech_synthesis_to_wave_file(config, translated_text, speaker_profile_id, target_language, audio_folder_name)

        return jsonify(synthesis_result)
    except Exception as e:
        print("Error encountered:", str(e))
        return jsonify({"error": str(e)})
    finally:
        # Optional Step 4: clean up, if you don't need this voice to synthesize more content.
        clean_up(config, project_id, consent_id, personal_voice_id)

def clean_up(config, project_id, consent_id, personal_voice_id):
    try:
        # Delete the personal voice and project
        customvoice.PersonalVoice.delete(config, personal_voice_id)
        customvoice.Project.delete(config, project_id)
        customvoice.Consent.delete(config, consent_id)
    except Exception as e:
        print(f"Clean up failed: {str(e)}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process', methods=['GET'])
def process_page():
    # Perform any processing logic here if needed
    return render_template('process.html')

# Function to check if a blob exists
def blob_exists(container_client, blob_name):
    try:
        container_client.get_blob_client(blob_name).get_blob_properties()
        return True
    except Exception:
        return False

# Function to upload file to Azure Blob Storage
def upload_to_blob_context(file_stream, blob_name):
    container_client = blob_service_client.get_container_client(container_name)
    
    # Check if the blob already exists
    if blob_exists(container_client, blob_name):
        raise Exception(f"Audio file '{blob_name}' already exists. Please choose another name.")

    # Upload blob
    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(file_stream)

    blob_url = blob_client.url
    return blob_url

# Function to check audio properties and convert if necessary
def check_and_convert_audio(file_stream):
    audio = AudioSegment.from_file(file_stream)
    
    if (
        audio.frame_rate != 24000 or  # Adjusted to match the required format
        audio.channels != 1 or
        audio.sample_width != 2
    ):
        # Convert to required format
        converted_audio = audio.set_frame_rate(24000).set_channels(1).set_sample_width(2)
        buffer = io.BytesIO()
        converted_audio.export(buffer, format="wav")
        buffer.seek(0)
        return buffer
    else:
        file_stream.seek(0)
        return file_stream

@app.route('/upload_context', methods=['POST'])
def upload_context_file():
    try:
        context_file = request.files['context_file']
        username = request.form.get('username').strip()
        context_file_name = secure_filename(f"VoiceTalentVerbalStatement_{username}.wav")
        
        # Check and convert file if necessary
        checked_file_stream = check_and_convert_audio(context_file.stream)

        # Upload file to Azure Blob Storage
        context_file_url = upload_to_blob_context(checked_file_stream, context_file_name)
        
        response = {
            "message": "Context file uploaded successfully",
            "context_file_url": context_file_url
        }
    except KeyError as e:
        response = {"error": f"Missing required parameter: {str(e)}"}
    except Exception as e:
        response = {"error": str(e)}

    return jsonify(response)

# Function to upload file to Azure Blob Storage with "directory" structure
def upload_to_blob_with_folder(file_stream, blob_name, folder_name):
    container_client = blob_service_client.get_container_client(container_name)
    
    # Check if the blob already exists in the specified folder
    if blob_exists(container_client, f"{folder_name}/{blob_name}"):
        raise Exception(f"File '{blob_name}' already exists in folder '{folder_name}'. Please choose another name.")

    # Convert audio to the required format
    converted_stream = convert_audio_to_required_format(file_stream)
    
    # Upload blob with "directory" prefix
    blob_client = container_client.get_blob_client(f"{folder_name}/{blob_name}")
    blob_client.upload_blob(converted_stream)

    blob_url = blob_client.url
    return blob_url

# Function to convert audio to required format (24 kHz, 16-bit PCM mono)
def convert_audio_to_required_format(file_stream):
    audio = AudioSegment.from_file(file_stream)
    
    if (
        audio.frame_rate != 24000 or
        audio.channels != 1 or
        audio.sample_width != 2
    ):
        # Convert to required format
        converted_audio = audio.set_frame_rate(24000).set_channels(1).set_sample_width(2)
        buffer = io.BytesIO()
        converted_audio.export(buffer, format="wav")
        buffer.seek(0)
        return buffer
    else:
        file_stream.seek(0)
        return file_stream

@app.route('/upload_sample_voice', methods=['POST'])
def upload_sample_voice_file():
    try:
        sample_voice_file = request.files['sample_voice_file']
        username = request.form.get('username').strip()
        sample_voice_file_name = secure_filename(sample_voice_file.filename)
        
        # Upload to Azure Blob Storage with "directory" structure
        blob_url = upload_to_blob_with_folder(sample_voice_file.stream, sample_voice_file_name, username)
        
        response = {
            "message": "Sample voice file uploaded successfully",
            "sample_voice_file_name": sample_voice_file_name,
            "sample_voice_blob_url": blob_url
        }
    except KeyError as e:
        response = {"error": f"Missing required parameter: {str(e)}"}
    except Exception as e:
        response = {"error": str(e)}
    
    return jsonify(response)


if __name__ == '__main__':
    app.run(debug=True)
