import subprocess
import sys


def test_import_does_not_load_consumers_engines_models_or_audio() -> None:
    code = (
        "import sys, utterplan; "
        "forbidden={'ttsready','spokenform','ssmdconvert','pykokoro','pipersynth',"
        "'kokorog2p','piperg2p','onnxruntime','numpy','soundfile'}; "
        "loaded=sorted({name.split('.')[0].lower() for name in sys.modules} & forbidden); "
        "print(loaded)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, text=True
    )
    assert result.stdout.strip() == "[]"


def test_non_identity_planning_loads_ttsready_lazily() -> None:
    code = (
        "import sys, utterplan; "
        "assert 'ttsready' not in sys.modules; "
        "utterplan.UtterancePlanner(utterplan.PlannerConfig(language='en-us')).plan('Hello.'); "
        "print('ttsready' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, text=True
    )
    assert result.stdout.strip() == "True"
