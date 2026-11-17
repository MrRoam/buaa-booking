from pathlib import Path

import numpy as np
import pytest

from src.captcha_recognition.matcher import _mask_features, _score_features, _score_masks


def test_cached_features_preserve_original_matching_scores():
    rng = np.random.default_rng(42)
    for _ in range(20):
        a = rng.integers(0, 2, size=(32, 32), dtype=np.uint8)
        b = rng.integers(0, 2, size=(32, 32), dtype=np.uint8)
        assert _score_features(_mask_features(a), _mask_features(b), .5, .3, .2) == pytest.approx(_score_masks(a, b), abs=1e-7)


def test_saved_real_glyph_keeps_color_information_and_rejects_wrong_target():
    from src.captcha_recognition.pipeline import CaptchaRecognizer
    recognizer = CaptchaRecognizer()
    image = Path(__file__).parent / 'fixtures/captcha-er-kuai-gao.png'
    positive = recognizer.verify(image, ['儿', '块', '高'])
    assert positive.complete
    er = positive.clicks[0].box
    assert 220 < er.x1 < 240 and 80 < er.y1 < 105
    assert not recognizer.verify(image, ['几', '块', '高']).complete
