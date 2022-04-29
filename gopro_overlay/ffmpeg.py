import contextlib
import itertools
import re
import subprocess
import sys
from array import array
from collections import namedtuple

from gopro_overlay.common import temporary_file
from gopro_overlay.dimensions import dimension_from, Dimension


def run(cmd, **kwargs):
    print("Running: " + " ".join(cmd))
    return subprocess.run(cmd, check=True, **kwargs)


def invoke(cmd, **kwargs):
    try:
        return run(cmd, **kwargs, text=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise IOError(f"Error: {cmd}\n stdout: {e.stdout}\n stderr: {e.stderr}")


StreamInfo = namedtuple("StreamInfo", ["audio", "video", "meta", "video_dimension", "rate", "duration"])


def cut_file(input, output, start, duration):
    streams = find_streams(input)

    maps = list(itertools.chain.from_iterable(
        [["-map", f"0:{stream}"] for stream in [streams.video, streams.audio, streams.meta]]))

    args = ["ffmpeg",
            "-y",
            "-i", input,
            "-map_metadata", "0",
            *maps,
            "-copy_unknown",
            "-ss", str(start),
            "-t", str(duration),
            "-c", "copy",
            output]

    print(args)

    run(args)


def join_files(filepaths, output):
    """only for joining parts of same trip"""

    streams = find_streams(filepaths[0])

    maps = list(itertools.chain.from_iterable(
        [["-map", f"0:{stream}"] for stream in [streams.video, streams.audio, streams.meta]]))

    with temporary_file() as commandfile:
        with open(commandfile, "w") as f:
            for path in filepaths:
                f.write(f"file '{path}\n")

        args = ["ffmpeg", "-hide_banner",
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", commandfile,
                "-map_metadata", "0",
                *maps,
                "-copy_unknown",
                "-c", "copy",
                output]
        print(f"Running {args}")
        run(args)


def find_streams(filepath, invoke=invoke):
    cmd = ["ffprobe", "-hide_banner", "-print_format", "json", "-show_streams", filepath]
    ffprobe_output = str(invoke(cmd).stdout)
    ffprobe_info = json.loads(ffprobe_output)
    #print("Loaded: " + ffprobe_output)

    video_stream = None
    video_dimension = None
    audio_stream = None
    meta_stream = None
    rate = None
    duration = None

    for stream in ffprobe_info["streams"]:
        if stream["codec_type"] == "video":
            video_stream = stream["index"]
            video_dimension = Dimension(stream["width"], stream["height"])
            rate = stream["r_frame_rate"]
            duration = float(stream["duration"])
        elif stream["codec_type"] == "audio":
            audio_stream = stream["index"]
        elif stream["codec_type"] == "data" and stream.get("codec_name", "") == "bin_data":
            meta_stream = stream["index"]

    print(f"video: {video_stream} audio: {audio_stream} meta: {meta_stream}")
    print(f"video_dimension: {video_dimension} rate: {rate} duration:{duration}s")

    if video_stream is None or audio_stream is None or meta_stream is None or video_dimension is None:
        raise IOError("Invalid File? The data stream doesn't seem to contain GoPro audio, video & metadata ")

    return StreamInfo(audio_stream, video_stream, meta_stream, video_dimension, rate, duration)



def load_gpmd_from(filepath):
    track = find_streams(filepath).meta
    if track:
        cmd = ["ffmpeg", '-y', '-i', filepath, '-codec', 'copy', '-map', '0:%d' % track, '-f', 'rawvideo', "-"]
        result = run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0:
            raise IOError(f"ffmpeg failed code: {result.returncode} : {result.stderr.decode('utf-8')}")
        arr = array("b")
        arr.frombytes(result.stdout)
        return arr


def ffmpeg_is_installed():
    try:
        invoke(["ffmpeg", "-version"])
        return True
    except FileNotFoundError:
        return False


def ffmpeg_libx264_is_installed():
    output = invoke(["ffmpeg", "-v", "quiet", "-codecs"]).stdout
    libx264s = [x for x in output.split('\n') if "libx264" in x]
    return len(libx264s) > 0


class FFMPEGOptions:

    def __init__(self, input=None, output=None):
        self.input = input if input is not None else []
        self.output = output if output is not None else ["-vcodec", "libx264", "-preset", "veryfast"]
        self.general = ["-hide_banner", "-loglevel", "info"]

    def set_input_options(self, options):
        self.input = options

    def set_output_options(self, options):
        self.output = options


def flatten(list_of_lists):
    result = []

    def flatten_part(part):
        for item in part:
            if type(item) == list:
                flatten_part(item)
            else:
                result.append(item)

    flatten_part(list_of_lists)
    return result


class FFMPEGGenerate:

    def __init__(self, output, overlay_size: Dimension, options: FFMPEGOptions = None, popen=subprocess.Popen):
        self.output = output
        self.options = options if options else FFMPEGOptions()
        self.overlay_size = overlay_size
        self.popen = popen

    @contextlib.contextmanager
    def generate(self):
        cmd = flatten([
            "ffmpeg",
            "-y",
            self.options.general,
            #"-loglevel", "info",
            "-f", "rawvideo",
            "-framerate", "10.0",
            "-s", f"{self.overlay_size.x}x{self.overlay_size.y}",
            "-pix_fmt", "rgba",
            "-i", "-",
            self.options.output,
            self.output
        ])
        print(f"Running FFMPEG as '{' '.join(cmd)}'")
        process = self.popen(cmd, stdin=subprocess.PIPE, stdout=None, stderr=None)
        try:
            yield process.stdin
        finally:
            process.stdin.flush()
        process.stdin.close()
        process.wait(120)


class FFMPEGOverlay:

    def __init__(self, input, output, overlay_size: Dimension, options: FFMPEGOptions = None, vsize=1080, redirect=None,
                 popen=subprocess.Popen):
        self.output = output
        self.input = input
        self.options = options if options else FFMPEGOptions()
        self.overlay_size = overlay_size
        self.vsize = vsize
        self.popen = popen
        self.redirect = redirect

    @contextlib.contextmanager
    def generate(self):
        if self.vsize == 1080:
            filter_extra = ""
        else:
            filter_extra = f",scale=-1:{self.vsize}"
        cmd = flatten([
            "ffmpeg",
            "-y",
            self.options.general,
            self.options.input,
            "-i", self.input,
            "-f", "rawvideo",
            "-framerate", "10.0",
            "-s", f"{self.overlay_size.x}x{self.overlay_size.y}",
            "-pix_fmt", "rgba",
            "-i", "-",
            "-filter_complex", f"[0:v][1:v]overlay{filter_extra}",
            self.options.output,
            self.output
        ])

        try:
            print(f"Running FFMPEG as '{' '.join(cmd)}'")
            if self.redirect:
                with open(self.redirect, "w") as std:
                    process = self.popen(cmd, stdin=subprocess.PIPE, stdout=std, stderr=std)
            else:
                process = self.popen(cmd, stdin=subprocess.PIPE, stdout=None, stderr=None)

            try:
                yield process.stdin
            finally:
                process.stdin.flush()
            process.stdin.close()
            # really long wait as FFMPEG processes all the mpeg input file - not sure how to prevent this atm
            process.wait(5 * 60)
        except FileNotFoundError:
            raise IOError("Unable to start the 'ffmpeg' process - is FFMPEG installed?") from None
        except BrokenPipeError:
            if self.redirect:
                print("FFMPEG Output:")
                with open(self.redirect) as f:
                    print("".join(f.readlines()), file=sys.stderr)
            raise IOError("FFMPEG reported an error - can't continue") from None


if __name__ == "__main__":
    print(ffmpeg_libx264_is_installed())
