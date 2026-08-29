from mineru_utils import parse_doc
from pathlib import Path
import os


def main():
    pdf_path = os.environ.get("SURVEY_AGENT_PDF_INPUT_DIR")
    output_path = os.environ.get("SURVEY_AGENT_MARKDOWN_OUTPUT_DIR")
    if not pdf_path or not output_path:
        raise SystemExit(
            "Set SURVEY_AGENT_PDF_INPUT_DIR and SURVEY_AGENT_MARKDOWN_OUTPUT_DIR before running this script."
        )

    pdf_paths_list = []
    for filename in os.listdir(pdf_path):
        if filename.endswith(".pdf"):
            pdf_paths_list.append(Path(os.path.join(pdf_path, filename)))

    parse_doc(
        path_list=pdf_paths_list,
        output_dir=output_path,
        lang="ch",
        backend="pipeline",
        method="auto",
    )


if __name__ == "__main__":
    main()
