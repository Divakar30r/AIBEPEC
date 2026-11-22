# XternalLoad

First chunking is done with external .csv file, note that column based chunking done (not row wise) as fields identification is primary for mapping. Chunks are stored in Postgres and a separate .env file being maintained for the same

Secondly , a RAG is done against the fields of the tables and the chunks, whichever relevant  
Run
1. ingest.py (no LLM, only embeddings/chunkings)
2. match_schema.py (this is the LLM one)
uv run --project .. python match_schema.py
This retrieves the matching chunks from Postgres, makes one call to the Hugging Face model, and prints JSON. The JSON has the CSV-to-FieldDesc.MD mappings, the unmapped columns and the data-quality issues.

match_schema.py needs ingest.py to have run first, because it reads the stored chunks. If you get a UnicodeEncodeError on the ₹ symbol, put PYTHONIOENCODING=utf-8 in front of the command.

# DAGRegistry

Generating a dump/registry based on the rules defined in json of PolRef.json and PolRefCount.json
Read the DAGRegistry/load_rules.txt for understanding JSON structure and idea behing Range_YYYYMMDD, Range_C , ListStr and such keywords
Final output is registry_dump.json (based on PolRef) and count_dump.json(based on PolRefCount). These both have to be re-generated if any changes in PolRef,PolRefCount, FieldDesc.MD and version numbers are maintained for the rules.
Based on these files data are generated in multiple rounds with attempts of self correction


