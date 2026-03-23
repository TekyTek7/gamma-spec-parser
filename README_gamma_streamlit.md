# Gamma Spec Streamlit App

This is a browser-based version of your Gamma Spec parser.

## What it does
- Upload one or more `.txt` Gamma Spec reports
- Or upload a `.zip` containing multiple `.txt` reports
- Parses the `NUCLIDE ISO 11929 REPORT` section
- Extracts sample size, nuclides, activity, and uncertainty
- Converts `Bq/unit` to `Bq/ml` using the chosen conversion factor
- Leaves `Bq/g` values unchanged
- Shows the results in a table
- Lets users download:
  - `gamma_summary.csv`
  - `gamma_results.zip` containing the CSV and plot PNGs

## Run locally

```bash
pip install -r requirements_gamma_streamlit.txt
streamlit run gamma_streamlit_app.py
```

## Deploy internally
A simple internal deployment path is:
- Create a Windows or Linux VM
- Install Python
- Install the requirements
- Run `streamlit run gamma_streamlit_app.py --server.port 8501`
- Put it behind your internal reverse proxy or internal DNS

## Deploy externally
For a quick proof-of-concept:
- Push the app files to GitHub
- Deploy on Streamlit Community Cloud
- Share the generated app link

## Files to deploy
- `gamma_streamlit_app.py`
- `requirements_gamma_streamlit.txt`
