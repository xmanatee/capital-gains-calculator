from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, StyleSheet1
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .model import CalculationEntry, CapitalGainsReport
from .util import round_decimal, strip_zeros


def build_styles() -> StyleSheet1:
    styles = StyleSheet1()
    styles.add(
        ParagraphStyle(
            name="Normal",
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            spaceAfter=6,
            textColor=colors.black,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Title",
            parent=styles["Normal"],
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
            fontSize=16,
            textColor=colors.darkblue,
            spaceAfter=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=colors.darkgreen,
            spaceBefore=10,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubSectionHeading",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            textColor=colors.darkred,
            leftIndent=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Indented",
            parent=styles["Normal"],
            leftIndent=20,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableHeader",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            alignment=TA_CENTER,
            textColor=colors.white,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableCell",
            parent=styles["Normal"],
            fontSize=9,
            alignment=TA_LEFT,
        )
    )
    return styles


def build_title_page(report: CapitalGainsReport, styles: StyleSheet1) -> list[Flowable]:
    story: list[Flowable] = []
    title_text = (
        f"Capital Gains Tax Calculations for {report.tax_year}-"
        f"{str((report.tax_year + 1) % 100).zfill(2)}"
    )
    story.append(Paragraph(title_text, styles["Title"]))
    story.append(Spacer(1, 12))
    return story


def identify_entry_type(symbol_key: str) -> tuple[str, str]:
    if symbol_key.startswith("sell$"):
        return ("Disposal", symbol_key[5:])
    if symbol_key.startswith("buy$"):
        return ("Acquisition", symbol_key[4:])
    if symbol_key.startswith("spin-off$"):
        return ("Spin-off Adjustment", symbol_key[9:])
    return ("Other", symbol_key)


def build_subsection_heading(
    entry_type: str,
    symbol: str,
    entries: list[CalculationEntry],
    styles: StyleSheet1,
    disposal_count: int,
    acquisition_count: int,
) -> Paragraph:
    overall_quantity = sum([e.quantity for e in entries], Decimal(0))
    if entry_type == "Disposal":
        disposed_amount = sum([e.amount for e in entries], Decimal(0))
        disposed_amount = round_decimal(disposed_amount)
        heading_str = (
            f"Disposal {disposal_count}: {strip_zeros(overall_quantity)} units "
            f"of {symbol} for £{disposed_amount:,.2f}"
        )
        return Paragraph(heading_str, styles["SubSectionHeading"])
    if entry_type == "Acquisition":
        acquisition_cost = sum([e.allowable_cost for e in entries], Decimal(0))
        acquisition_cost = round_decimal(acquisition_cost)
        heading_str = (
            f"Acquisition {acquisition_count}: {strip_zeros(overall_quantity)} units "
            f"of {symbol} for £{acquisition_cost:,.2f}"
        )
        return Paragraph(heading_str, styles["SubSectionHeading"])
    if entry_type == "Spin-off Adjustment":
        spin_off = entries[0].spin_off
        if spin_off is not None:
            heading_str = (
                f"Spin-off Adjustment {acquisition_count}: "
                f"{spin_off.source} cost adjusted due to {spin_off.dest} shares"
            )
        else:
            heading_str = (
                f"Spin-off Adjustment {acquisition_count}: (no spin-off info found)"
            )
        return Paragraph(heading_str, styles["SubSectionHeading"])
    heading_str = f"{entry_type}: {symbol}"
    return Paragraph(heading_str, styles["SubSectionHeading"])


def build_entry_details_paragraphs(
    entry_type: str, entries: list[CalculationEntry], styles: StyleSheet1
) -> list[Flowable]:
    paras: list[Flowable] = []
    overall_quantity = sum([e.quantity for e in entries], Decimal(0))
    overall_fees = sum([e.fees for e in entries], Decimal(0))

    if entry_type == "Disposal":
        first_amount = entries[0].amount
        first_quantity = entries[0].quantity
        unit_price = Decimal(0)
        if first_quantity != 0:
            unit_price = round_decimal(first_amount / first_quantity)
        fee_str = (
            f", after £{round_decimal(overall_fees):,.2f} fees"
            if overall_fees > 0
            else ""
        )
        paras.append(
            Paragraph(f"Unit price: £{unit_price:,.2f}{fee_str}", styles["Indented"])
        )

    elif entry_type == "Acquisition":
        total_cost = sum([e.allowable_cost for e in entries], Decimal(0))
        unit_cost = Decimal(0)
        if overall_quantity != 0:
            unit_cost = round_decimal(total_cost / overall_quantity)
        fee_str = (
            f", including £{round_decimal(overall_fees):,.2f} fees"
            if overall_fees > 0
            else ""
        )
        paras.append(
            Paragraph(f"Unit price: £{unit_cost:,.2f}{fee_str}", styles["Indented"])
        )

    return paras


def build_table_columns_for_entry(
    entry_type: str, entries: list[CalculationEntry]
) -> list[str]:
    columns = ["Rule Type", "Quantity"]
    if entry_type == "Disposal":
        columns.append("Amount (£)")
        columns.append("Allowable Cost (£)")
        columns.append("Gain/Loss (£)")
    elif entry_type in {"Acquisition", "Spin-off Adjustment"}:
        columns.append("Allowable Cost (£)")
    include_section_104 = any(e.rule_type.name == "SECTION_104" for e in entries)
    if include_section_104:
        columns.append("New Quantity")
        columns.append("New Pool Cost (£)")
    return columns


def build_table_data_for_entries(
    columns: list[str], entries: list[CalculationEntry], styles: StyleSheet1
) -> list[list[Flowable]]:
    if not entries:
        return []
    header_cells: list[Flowable] = [
        Paragraph(col, styles["TableHeader"]) for col in columns
    ]
    table_data: list[list[Flowable]] = [header_cells]

    for entry in entries:
        row_cells: list[Flowable] = []
        rule_type_str = entry.rule_type.name.replace("_", " ")
        row_cells.append(Paragraph(rule_type_str, styles["TableCell"]))
        row_cells.append(Paragraph(strip_zeros(entry.quantity), styles["TableCell"]))

        if "Amount (£)" in columns:
            amount_str = f"£{round_decimal(entry.amount):,.2f}"
            row_cells.append(Paragraph(amount_str, styles["TableCell"]))

        if "Allowable Cost (£)" in columns:
            ac_str = f"£{round_decimal(entry.allowable_cost):,.2f}"
            row_cells.append(Paragraph(ac_str, styles["TableCell"]))

        if "Gain/Loss (£)" in columns:
            gain_str = f"£{round_decimal(entry.gain):,.2f}"
            row_cells.append(Paragraph(gain_str, styles["TableCell"]))

        if "New Quantity" in columns:
            if entry.rule_type.name == "SECTION_104" and entry.new_quantity is not None:
                row_cells.append(
                    Paragraph(strip_zeros(entry.new_quantity), styles["TableCell"])
                )
            else:
                row_cells.append(Paragraph("-", styles["TableCell"]))

        if "New Pool Cost (£)" in columns:
            if (
                entry.rule_type.name == "SECTION_104"
                and entry.new_pool_cost is not None
            ):
                npc_str = f"£{round_decimal(entry.new_pool_cost):,.2f}"
                row_cells.append(Paragraph(npc_str, styles["TableCell"]))
            else:
                row_cells.append(Paragraph("-", styles["TableCell"]))

        table_data.append(row_cells)
    return table_data


def get_table_style() -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
        ]
    )


def build_running_total_paragraph(
    gain_val: Decimal, total_gain: Decimal, total_loss: Decimal, styles: StyleSheet1
) -> list[Flowable]:
    result: list[Flowable] = []
    if gain_val > 0:
        gain_str = f"Gain: £{gain_val:,.2f}"
        overall_str = f"Capital gain to date: £{total_gain:,.2f}"
        result.append(Paragraph(gain_str, styles["Indented"]))
        result.append(Paragraph(overall_str, styles["Indented"]))
    elif gain_val < 0:
        loss_str = f"Loss: £{-gain_val:,.2f}"
        overall_str = f"Capital loss to date: £{total_loss:,.2f}"
        result.append(Paragraph(loss_str, styles["Indented"]))
        result.append(Paragraph(overall_str, styles["Indented"]))
    return result


def build_summary_section(
    report: CapitalGainsReport,
    styles: StyleSheet1,
    disposal_count: int,
    acquisition_count: int,
    total_gain: Decimal,
    total_loss: Decimal,
) -> list[Flowable]:
    return [
        Spacer(1, 12),
        Paragraph("Overall Summary", styles["SectionHeading"]),
        Spacer(1, 3),
        Paragraph(
            f"<b>Number of acquisitions:</b> {acquisition_count}", styles["Indented"]
        ),
        Paragraph(f"<b>Number of disposals:</b> {disposal_count}", styles["Indented"]),
        Paragraph(
            f"<b>Total disposal proceeds:</b> £{report.disposal_proceeds:,.2f}",
            styles["Indented"],
        ),
        Paragraph(
            f"<b>Total capital gain before loss:</b> £{total_gain:,.2f}",
            styles["Indented"],
        ),
        Paragraph(f"<b>Total capital loss:</b> £{total_loss:,.2f}", styles["Indented"]),
        Paragraph(
            f"<b>Total capital gain after loss:</b> £{(total_gain - total_loss):,.2f}",
            styles["Indented"],
        ),
    ]


def build_transaction_section(
    report: CapitalGainsReport, styles: StyleSheet1
) -> tuple[list[Flowable], Decimal, Decimal, int, int]:
    story: list[Flowable] = []
    total_gain = Decimal(0)
    total_loss = Decimal(0)
    acquisition_count = 0
    disposal_count = 0

    for date_index, symbol_dict in sorted(report.calculation_log.items()):
        date_str = date_index.strftime("%d %B %Y")
        story.append(Paragraph(date_str, styles["SectionHeading"]))
        story.append(Spacer(1, 3))

        for symbol_key, entries in symbol_dict.items():
            entry_type, symbol = identify_entry_type(symbol_key)
            if entry_type == "Disposal":
                disposal_count += 1
            elif entry_type in ["Acquisition", "Spin-off Adjustment"]:
                acquisition_count += 1

            heading_para = build_subsection_heading(
                entry_type, symbol, entries, styles, disposal_count, acquisition_count
            )
            story.append(heading_para)

            details_paras = build_entry_details_paragraphs(entry_type, entries, styles)
            story.extend(details_paras)

            table_cols = build_table_columns_for_entry(entry_type, entries)
            table_data = build_table_data_for_entries(table_cols, entries, styles)

            if table_data:
                table_style = get_table_style()
                report_table = Table(table_data, repeatRows=1, hAlign="LEFT")
                report_table.setStyle(table_style)
                story.append(report_table)
                story.append(Spacer(1, 12))

            if entry_type == "Disposal":
                gain_val = sum([e.gain for e in entries], Decimal(0))
                gain_val = round_decimal(gain_val)
                if gain_val > 0:
                    total_gain += gain_val
                else:
                    total_loss += -gain_val
                running_total = build_running_total_paragraph(
                    gain_val, total_gain, total_loss, styles
                )
                story.extend(running_total)

    return story, total_gain, total_loss, acquisition_count, disposal_count


def build_entire_story(
    report: CapitalGainsReport, styles: StyleSheet1
) -> list[Flowable]:
    story: list[Flowable] = []
    story.extend(build_title_page(report, styles))

    (
        transaction_section,
        total_gain,
        total_loss,
        acquisition_count,
        disposal_count,
    ) = build_transaction_section(report, styles)
    story.extend(transaction_section)

    summary_section = build_summary_section(
        report, styles, disposal_count, acquisition_count, total_gain, total_loss
    )
    story.extend(summary_section)

    return story


def render_calculations(report: CapitalGainsReport, output_path: Path) -> None:
    if not output_path.parent.exists():
        output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=18,
    )

    styles = build_styles()
    story = build_entire_story(report, styles)
    doc.build(story)
