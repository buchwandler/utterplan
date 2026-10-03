import subprocess
import sys


def test_import_does_not_load_consumers_engines_models_or_audio() -> None:
    code = (
        "import sys, utterplan; "
        "forbidden={'ttsready','readio','ssmdconvert','pykokoro','pipersynth',"
        "'kokorog2p','piperg2p','onnxruntime','numpy','soundfile'}; "
        "loaded=sorted({name.split('.')[0].lower() for name in sys.modules} & forbidden); "
        "print(loaded)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, text=True
    )
    assert result.stdout.strip() == "[]"
