import subprocess
import os
import argparse
from moviepy.video.io.ffmpeg_tools import ffmpeg_extract_subclip, ffmpeg_merge_video_audio
import boto3
from pydub import AudioSegment
from datetime import datetime
import math
from tqdm import tqdm
import time
from datetime import timedelta

final_video_file_name = None
speech_folder = "speech"
if not os.path.exists(speech_folder):
    os.mkdir(speech_folder)

hindi_subtitles_folder = "hindi_subtitles"
if not os.path.exists(hindi_subtitles_folder):
    os.mkdir(hindi_subtitles_folder)

final_videos_folder = "final_videos"
if not os.path.exists(final_videos_folder):
    os.mkdir(final_videos_folder)

audios_folder = "audios"
if not os.path.exists(audios_folder):
    os.mkdir(audios_folder)


def cut_video(video_file_path):
    output_folder = "short_videos"
    ffmpeg_extract_subclip(video_file_path, 0, 12,
                           targetname=os.path.join(output_folder, os.path.basename(video_file_path)))


def remove_audio(video_file_path):
    no_audio_video_path = os.path.join(final_videos_folder, os.path.basename(video_file_path.replace(".mp4", "_noaudio.mp4")))
    command = 'ffmpeg -i {video_file} -c copy -an {output_file}'.format(
        video_file=video_file_path,
        output_file=no_audio_video_path
    )
    subprocess.call(command, shell=True)

    return no_audio_video_path


def get_audio_from_video(video_file_path):
    audio_file_path = os.path.join(audios_folder, os.path.splitext(os.path.basename(video_file_path))[0] + ".wav")

    command = "ffmpeg -i {} -ab 160k -ac 2 -ar 44100 -vn {}".format(video_file_path, audio_file_path)
    subprocess.call(command, shell=True)


def isInt(s):
    try:
        int(s)
        return True
    except ValueError:
        return False


def process_english_subtitles(subtitles_file_path):
    lines = open(subtitles_file_path, 'r').read().splitlines()
    english_subtitles = []
    line_seperators = [".", "?", "!"]

    i = 0
    start_time = None
    text = ""
    while i < len(lines):
        line = lines[i]
        if isInt(line):
            i += 1
            line = lines[i]
            start_time_str = line.split(" ")[0].split(".")[0]
            end_time_str = line.split(" ")[-1].split(".")[0]
            if start_time is None:
                start_time = start_time_str
            while len(lines) > i + 1 and lines[i + 1] != "":
                i += 1
                text += " " + lines[i]
            i += 1
            for seperator in line_seperators:
                if seperator in text:
                    english_subtitles.append((start_time, text.split(seperator)[0] + seperator))
                    text = seperator.join(text.split(seperator)[1:])
                    start_time = end_time_str
                    break
        i += 1

    return english_subtitles


def translate_text(english_subtitles, subtitles_file_path):
    hindi_subtitles = []
    translate = boto3.client(service_name='translate', region_name='us-east-2', use_ssl=True)
    for timestr, english_subtitle in tqdm(english_subtitles):
        result = translate.translate_text(Text=english_subtitle,
                                          SourceLanguageCode="en",
                                          TargetLanguageCode="hi")
        print('TranslatedText: ' + result.get('TranslatedText'))
        hindi_subtitles.append((timestr, result.get('TranslatedText')))

    # write to file
    file_text = ""
    for time_stamp, subtitle in hindi_subtitles:
        file_text += "{},{}\n".format(time_stamp, subtitle)
    f = open(os.path.join(hindi_subtitles_folder, os.path.basename(subtitles_file_path)), 'w')
    f.write(file_text)
    f.close()

    return hindi_subtitles


def synthesize_speech(hindi_subtitles):
    speech_files = []
    polly_client = boto3.client('polly')
    for time_stamp, hindi_subtitle in tqdm(hindi_subtitles):
        response = polly_client.synthesize_speech(
            Engine='standard',
            LanguageCode='hi-IN',
            OutputFormat='mp3',
            Text=hindi_subtitle,
            VoiceId='Aditi'
        )
        output_file_name = os.path.join(speech_folder, '{}.mp3'.format(time_stamp))
        file = open(output_file_name, 'wb')
        file.write(response['AudioStream'].read())
        file.close()
        speech_files.append((time_stamp, output_file_name))

    return speech_files


def generate_hindi_subtitle_file(hindi_subtitles):
    subtitles_text = ""
    dot_text = ".000"

    for i in range(len(hindi_subtitles)):
        # add number
        subtitles_text += str(i+1)
        subtitles_text += "\n"

        # add time stamp
        subtitles_text += hindi_subtitles[i][0] + dot_text
        subtitles_text += " --> "
        if i == len(hindi_subtitles) - 1:
            subtitles_text += hindi_subtitles[i][0][:-2] + "60" + dot_text
        else:
            subtitles_text += hindi_subtitles[i+1][0] + dot_text
        subtitles_text += "\n"

        # add text
        subtitles_text += hindi_subtitles[i][1]
        subtitles_text += "\n\n"

    f = open(os.path.join(final_videos_folder, os.path.splitext(os.path.basename(final_video_file_name))[0])+".srt", 'w')
    f.write(subtitles_text)
    f.close()



def combine_speech_files(speech_files, hindi_subtitles):
    silence_file_path = os.path.join(".", "silence.mp3")
    silence_file = AudioSegment.from_mp3(silence_file_path)

    audio_files = [((datetime.strptime(time_stamp, "%H:%M:%S") - datetime(1900, 1, 1)).total_seconds(),
                    AudioSegment.from_mp3(speech_file))
                   for time_stamp, speech_file in speech_files]

    final_audio_file = silence_file[:audio_files[0][0] * 1000]
    for i in tqdm(range(len(audio_files))):
        start_second, audio_file = audio_files[i]
        hindi_subtitles[i] = ((datetime.strptime("00:00:00", "%H:%M:%S") + timedelta(0, int(final_audio_file.duration_seconds))).strftime("%H:%M:%S"), hindi_subtitles[i][1])
        if final_audio_file.duration_seconds < start_second:
            final_audio_file += silence_file_path[math.floor(start_second - final_audio_file.duration_seconds) * 1000]
        final_audio_file += audio_file

    final_audio_save_path = os.path.join(speech_folder, "final_speech.mp3")
    final_audio_file.export(final_audio_save_path, format="mp3")

    print("[Generating Hindi Subtitles]")
    generate_hindi_subtitle_file(hindi_subtitles)

    return final_audio_save_path


def embed_audio(video_path, speech_file):
    new_video_path = os.path.join(final_videos_folder, "final_" + os.path.basename(video_path))
    command = "ffmpeg -i {video_file} -i {audio_file} -codec copy {output_file}".format(
        video_file=video_path,
        audio_file=speech_file,
        output_file=new_video_path
    )
    subprocess.call(command, shell=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--video", required=True, help="video file path")
    parser.add_argument("-s", "--subtitles", required=True, help="subtitles file path")
    args = vars(parser.parse_args())


    print("[STARTED]")
    start_time = time.time()

    # cut the video to short clip
    # cut_video(video_file_path=args["video"])

    # get the audio from given video
    print("[Extracting the Audio]...")
    get_audio_from_video(args["video"])

    # remove audio and create copy of original video
    print("[Removing Original Audio from Video]...")
    no_audio_video_path = remove_audio(args["video"])

    final_video_file_name = "final_" + os.path.basename(no_audio_video_path)

    # get the english subtitles
    print("[Processing Subtitles]...")
    english_subtitles = process_english_subtitles(args["subtitles"])
    # english_subtitles = english_subtitles[:2]

    # get the translated text
    print("[Translating]...")
    hindi_subtitles = translate_text(english_subtitles, subtitles_file_path=args["subtitles"])
    # lines = open(os.path.join(hindi_subtitles_folder, os.path.basename(args["subtitles"])), 'r').read().splitlines()
    # hindi_subtitles = [(line.split(",")[0], ",".join(line.split(",")[1:])) for line in lines]

    # get the speech output of text
    print("[Generating Speech]...")
    speech_files = synthesize_speech(hindi_subtitles)
    # speech_files = [
    #     ("00:00:01", "speech/00:00:01.mp3"), ("00:00:06", "speech/00:00:06.mp3"), ("00:00:08", "speech/00:00:08.mp3")
    # ]

    # combine speech files
    print("[Combining Speech]...")
    final_audio_save_path = combine_speech_files(speech_files, hindi_subtitles)

    # embed the speech into video
    print("[Embedding Speech Into Video]")
    embed_audio(no_audio_video_path, final_audio_save_path)

    # remove video with no audio
    os.remove(no_audio_video_path)

    end_time = time.time()
    print("Time elapsed: ", int(end_time - start_time), "seconds")
