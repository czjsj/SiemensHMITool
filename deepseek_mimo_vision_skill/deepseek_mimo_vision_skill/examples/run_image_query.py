"""Example: directly call MiMo vision bridge without DeepSeek."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from mimo_vision import analyze_with_mimo


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python examples/run_image_query.py <image_path_or_url> <question>")
        raise SystemExit(2)

    image = sys.argv[1]
    question = sys.argv[2]
    image_type = "url" if image.startswith(("http://", "https://")) else "path"

    result = analyze_with_mimo(
        {
            "images": [{"type": image_type, "value": image}],
            "task": question,
            "output_schema": "detailed",
            "language": "zh-CN",
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
