# Fanoos Data Processing Pipeline

This task is part of the Fanoos data processing pipeline.

The pipeline takes job posting data collected by web scrapers and processes it into a structured format. An LLM is used to extract the required information from the job posting text, and Pydantic is used to validate the extracted data.

## What the pipeline does

The main flow is:

1. Receive job posting data from web scrapers.
2. Store and manage the raw ads.
3. Send the job posting text to the LLM.
4. Extract the required fields.
5. Validate the extracted data with Pydantic.
6. Save the processed data.

The pipeline also handles duplicate ads and ads that cannot be processed.

## Main Files

* `run_extraction.py` - runs the main extraction process.
* `llm_config.py` - contains the LLM configuration.
* `extraction_prompt.md` - contains the prompt used for data extraction.
* `schema.py` - defines the Pydantic schema for the extracted data.
* `ad_store.py` - manages raw ads, processed ads, dropped ads, and duplicates.

## Input

The input data comes from the web scraping part of the Fanoos project.

Each job ad contains information such as:

* `document_id`
* `collector`
* `collected_at`
* `text`

Example:

```json
{
  "document_id": "job_bot_0001",
  "collector": "bot",
  "collected_at": "2026-08-30",
  "text": "Job posting text..."
}
```

## Output

The processed job ads are saved as JSONL data using the fields defined in `schema.py`.

Ads that cannot be processed are stored separately with information about the reason and the processing attempts.

Duplicate ads are also detected and stored separately.

## Notes

API keys and other private settings should be stored in environment variables.
