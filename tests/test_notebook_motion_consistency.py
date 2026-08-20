import json
from pathlib import Path


def test_notebook_uses_current_motion_summary_symbols():
    notebook = Path(__file__).resolve().parents[1] / 'modules' / 'cv-pipeline' / 'cv_pipeline_lab.ipynb'
    payload = json.loads(notebook.read_text(encoding='utf-8'))
    text = ''.join(''.join(cell.get('source', [])) for cell in payload['cells'])

    assert 'flow_summary_a' not in text, 'Notebook still contains stale motion summary symbols'
    assert 'choose_motion_roi' in text, 'Notebook must include the vehicle-centered ROI logic'
    assert 'translation_m' in text, 'Notebook must include the 3D motion proxy metrics'
    assert "if 'curr_frame_idx' not in globals()" in text, 'Notebook must guard missing frame state'
