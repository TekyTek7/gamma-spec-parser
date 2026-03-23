from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st


OUTPUT_COLUMNS = [
    'filename',
    'sample_size_value',
    'sample_size_unit',
    'nuclide',
    'activity_orig',
    'activity_unit_orig',
    'uncertainty',
    'activity_converted',
    'converted_unit',
    'notes',
]


@st.cache_data(show_spinner=False)
def parse_sample_size(text: str):
    m = re.search(r"Sample Size\s*:\s*([0-9Ee+\-\.]+)\s*([A-Za-z%]+)", text)
    if m:
        return float(m.group(1)), m.group(2)
    return None, None


@st.cache_data(show_spinner=False)
def find_nuclides_block_lines(lines: tuple[str, ...]):
    for i, line in enumerate(lines):
        if 'N U C L I D E' in line and '1 1 9 2 9' in line:
            return i
    return None


@st.cache_data(show_spinner=False)
def detect_activity_unit_near(lines: tuple[str, ...], start_idx: int | None):
    if start_idx is None:
        return None

    start = max(0, start_idx - 20)
    end = min(len(lines), start_idx + 20)
    for j in range(start, end):
        line = lines[j]
        if 'ACTIVITY' in line.upper() or 'ACTIVIT' in line.upper():
            clean = line.replace('(', ' ').replace(')', ' ')
            m = re.search(r'Bq\s*/\s*([A-Za-z%]+)', clean, re.IGNORECASE)
            if m:
                return m.group(1).lower()
            low = clean.lower()
            if '/g' in low or ' bq / g' in low or 'bq/g' in low:
                return 'g'
            if '/unit' in low or ' bq / unit' in low or 'bq/unit' in low:
                return 'unit'

    for line in lines:
        low = line.lower()
        if 'bq' in low and '/g' in low:
            return 'g'
        if 'bq' in low and '/unit' in low:
            return 'unit'

    return None


@st.cache_data(show_spinner=False)
def parse_nuclide_rows(lines: tuple[str, ...], start_idx: int | None):
    rows = []
    if start_idx is None:
        return rows

    table_start = None
    for i in range(start_idx, len(lines)):
        if 'Nuclide' in lines[i] and 'MDA' in lines[i]:
            table_start = i + 2
            break

    if table_start is None:
        return rows

    for i in range(table_start, len(lines)):
        line = lines[i].strip()
        if not line or (not line.startswith('+') and not line.startswith('>')):
            if rows:
                break
            continue

        toks = line[1:].strip().split()
        if len(toks) >= 2:
            nuclide = toks[0]
            try:
                best_est_unc = float(toks[-1].replace('D', 'E'))
                best_est_act = float(toks[-2].replace('D', 'E'))
                rows.append((nuclide, best_est_act, best_est_unc, line))
            except (ValueError, IndexError):
                continue

    return rows


@st.cache_data(show_spinner=False)
def process_report_text(filename: str, text: str, ml_per_unit: float = 4.8):
    sample_size_value, sample_size_unit = parse_sample_size(text)
    lines = tuple(text.splitlines())
    header_idx = find_nuclides_block_lines(lines)
    if header_idx is None:
        raise ValueError('NUCLIDE ISO 11929 REPORT section not found')

    activity_unit = detect_activity_unit_near(lines, header_idx)
    nuclide_rows = parse_nuclide_rows(lines, header_idx)
    if not nuclide_rows:
        raise ValueError('Nuclide table found but no data rows were parsed')

    summary_rows = []
    act_unit_norm = (activity_unit or 'unknown').lower()

    for nuclide, activity, uncertainty, _raw in nuclide_rows:
        if 'unit' in act_unit_norm:
            converted = activity / ml_per_unit
            converted_unit = 'Bq/ml'
            notes = f'converted Bq/unit -> Bq/ml (liquid, {ml_per_unit:g} ml per unit)'
        elif 'g' in act_unit_norm:
            converted = activity
            converted_unit = 'Bq/g'
            notes = 'original Bq/g (solid sample)'
        else:
            converted = activity
            converted_unit = activity_unit or 'unknown'
            notes = f'unknown activity unit {activity_unit}; left unchanged'

        summary_rows.append(
            {
                'filename': filename,
                'sample_size_value': sample_size_value,
                'sample_size_unit': sample_size_unit,
                'nuclide': nuclide,
                'activity_orig': activity,
                'activity_unit_orig': activity_unit or 'unknown',
                'uncertainty': uncertainty,
                'activity_converted': converted,
                'converted_unit': converted_unit,
                'notes': notes,
            }
        )

    return summary_rows


def build_csv_bytes(rows: list[dict]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=OUTPUT_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode('utf-8')


def figure_for_sample(items: list[dict], sample_name: str):
    items_sorted = sorted(
        items,
        key=lambda x: x['activity_converted'] if x['activity_converted'] is not None else 0,
        reverse=True,
    )
    nuclides = [i['nuclide'] for i in items_sorted]
    vals = [i['activity_converted'] for i in items_sorted]
    unit = items_sorted[0]['converted_unit'] if items_sorted else 'Bq'

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(nuclides, vals)
    ax.set_ylabel(unit)
    ax.set_title(f'{sample_name} - activities ({unit})')
    ax.tick_params(axis='x', rotation=90)

    for bar, val in zip(bars, vals):
        height = bar.get_height()
        if val is None:
            label_text = ''
        elif val >= 100:
            label_text = f'{val:.0f}'
        elif val >= 10:
            label_text = f'{val:.1f}'
        else:
            label_text = f'{val:.2f}'
        if label_text:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                height,
                label_text,
                ha='center',
                va='bottom',
                fontsize=9,
            )

    plt.xticks(rotation=90)
    plt.tight_layout()
    return fig


def figure_to_png_bytes(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def collect_uploaded_txt_files(uploaded_files) -> list[tuple[str, str]]:
    reports: list[tuple[str, str]] = []

    for uploaded in uploaded_files:
        name_lower = uploaded.name.lower()
        payload = uploaded.getvalue()

        if name_lower.endswith('.txt'):
            reports.append((uploaded.name, payload.decode('utf-8', errors='ignore')))
        elif name_lower.endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                for member in zf.infolist():
                    if member.is_dir() or not member.filename.lower().endswith('.txt'):
                        continue
                    reports.append(
                        (
                            Path(member.filename).name,
                            zf.read(member).decode('utf-8', errors='ignore'),
                        )
                    )
    return reports


def build_results_zip(rows: list[dict]) -> bytes:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['filename']].append(row)

    csv_bytes = build_csv_bytes(rows)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('gamma_summary.csv', csv_bytes)
        for filename, items in grouped.items():
            fig = figure_for_sample(items, filename)
            png_bytes = figure_to_png_bytes(fig)
            zf.writestr(f"plots/{Path(filename).stem}.png", png_bytes)
    zip_buffer.seek(0)
    return zip_buffer.getvalue()


def main():
    st.set_page_config(page_title='Gamma Spec Report Parser', layout='wide')
    st.title('Gamma Spec Report Parser')
    st.write(
        'Upload one or more GENIE-style Gamma Spec `.txt` reports, or upload a `.zip` containing reports. '
        'The app will parse nuclides, convert units where needed, generate a summary table, and create activity plots.'
    )

    with st.sidebar:
        st.header('Settings')
        ml_per_unit = st.number_input(
            'Liquid conversion factor (ml per unit)',
            min_value=0.0001,
            value=4.8,
            step=0.1,
            help='Used when the report activity unit is Bq/unit. Converted result = activity / ml per unit.',
        )
        st.caption('Solid samples reported in Bq/g are left unchanged.')

    uploaded_files = st.file_uploader(
        'Upload report files',
        type=['txt', 'zip'],
        accept_multiple_files=True,
    )

    if not uploaded_files:
        st.info('Upload one or more `.txt` files or a `.zip` archive to begin.')
        return

    reports = collect_uploaded_txt_files(uploaded_files)
    if not reports:
        st.error('No `.txt` reports were found in the uploaded selection.')
        return

    all_rows: list[dict] = []
    errors: list[tuple[str, str]] = []

    for filename, text in reports:
        try:
            rows = process_report_text(filename, text, ml_per_unit)
            all_rows.extend(rows)
        except Exception as exc:
            errors.append((filename, str(exc)))

    if not all_rows:
        st.error('No reports were successfully parsed.')
        if errors:
            with st.expander('Parsing errors'):
                for filename, err in errors:
                    st.write(f'- **{filename}**: {err}')
        return

    df = pd.DataFrame(all_rows, columns=OUTPUT_COLUMNS)

    col1, col2, col3 = st.columns(3)
    col1.metric('Files parsed', df['filename'].nunique())
    col2.metric('Nuclide rows', len(df))
    col3.metric('Failed files', len(errors))

    if errors:
        with st.expander('Parsing errors'):
            for filename, err in errors:
                st.write(f'- **{filename}**: {err}')

    st.subheader('Summary table')
    st.dataframe(df, use_container_width=True)

    csv_bytes = build_csv_bytes(all_rows)
    zip_bytes = build_results_zip(all_rows)

    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            'Download CSV summary',
            data=csv_bytes,
            file_name='gamma_summary.csv',
            mime='text/csv',
            use_container_width=True,
        )
    with dl2:
        st.download_button(
            'Download CSV + plots ZIP',
            data=zip_bytes,
            file_name='gamma_results.zip',
            mime='application/zip',
            use_container_width=True,
        )

    st.subheader('Activity plots')
    grouped = defaultdict(list)
    for row in all_rows:
        grouped[row['filename']].append(row)

    sample_names = sorted(grouped.keys())
    selected_sample = st.selectbox('Choose a sample to preview', sample_names)
    fig = figure_for_sample(grouped[selected_sample], selected_sample)
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

    with st.expander('Deployment notes'):
        st.markdown(
            '- For internal use, deploy this app on a company VM or internal server.\n'
            '- For a quick external proof-of-concept, Streamlit Community Cloud is the fastest route.\n'
            '- If reports are sensitive, avoid public hosting unless IT approves it.'
        )


if __name__ == '__main__':
    main()
