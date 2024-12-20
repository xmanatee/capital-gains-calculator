# calc/src/python/capital-gains-calculator/cgt_calc/render_html.py

from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .model import CapitalGainsReport
from .util import round_decimal, strip_zeros


def render_calculations(
    report: CapitalGainsReport,
    output_path: Path,
) -> None:
    if not output_path.parent.exists():
        output_path.parent.mkdir(parents=True, exist_ok=True)

    # Setup ReportLab document
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=18,
    )

    # Define styles
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="CenterHeading",
            alignment=TA_CENTER,
            fontSize=18,
            spaceAfter=20,
            textColor=colors.darkblue,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            fontSize=14,
            spaceAfter=12,
            spaceBefore=12,
            textColor=colors.darkgreen,
            leftIndent=0,
            rightIndent=0,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubSectionHeading",
            fontSize=12,
            spaceAfter=6,
            spaceBefore=6,
            textColor=colors.darkred,
            leftIndent=20,
            rightIndent=0,
        )
    )
    styles.add(
        ParagraphStyle(
            name="NormalIndent",
            fontSize=10,
            spaceAfter=6,
            leftIndent=40,
            textColor=colors.black,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableHeader",
            fontSize=10,
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
            textColor=colors.white,
            backColor=colors.darkblue,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableCell",
            fontSize=9,
            alignment=TA_LEFT,
            textColor=colors.black,
        )
    )

    story: list[Flowable] = []

    # Title
    title = (
        f"Capital Gains Tax Calculations for {report.tax_year}-"
        f"{str((report.tax_year + 1) % 100).zfill(2)}"
    )
    story.append(Paragraph(title, styles["CenterHeading"]))
    story.append(Spacer(1, 12))

    # Initialize totals
    total_gain = Decimal(0)
    total_loss = Decimal(0)
    acquisition_count = 0
    disposal_count = 0

    # Iterate over calculation log
    for date_index, symbol_dict in sorted(report.calculation_log.items()):
        # Section for each date
        date_str = date_index.strftime("%d %B %Y")
        story.append(Paragraph(date_str, styles["SectionHeading"]))
        story.append(Spacer(1, 6))

        for symbol_key, entries in symbol_dict.items():
            # Determine the type of entry
            if symbol_key.startswith("sell$"):
                entry_type = "Disposal"
                symbol = symbol_key[5:]
                disposal_count += 1
            elif symbol_key.startswith("buy$"):
                entry_type = "Acquisition"
                symbol = symbol_key[4:]
                acquisition_count += 1
            elif symbol_key.startswith("spin-off$"):
                entry_type = "Spin-off Adjustment"
                symbol = symbol_key[9:]
                acquisition_count += 1
            else:
                entry_type = "Other"
                symbol = symbol_key

            # Subsection heading
            if entry_type == "Disposal":
                disposed_amount = round_decimal(sum(e.amount for e in entries), 2)
                disposed_amount_str = f"£{disposed_amount:,.2f}"
                story.append(
                    Paragraph(
                        f"{entry_type} {disposal_count}: "
                        f"{strip_zeros(sum(e.quantity for e in entries))} units of"
                        f" {symbol} for {disposed_amount_str}",
                        styles["SubSectionHeading"],
                    )
                )
            elif entry_type == "Acquisition":
                acquisition_cost = round_decimal(entries[0].allowable_cost, 2)
                acquisition_cost_str = f"£{acquisition_cost:,.2f}"
                story.append(
                    Paragraph(
                        f"{entry_type} {acquisition_count}: "
                        f"{strip_zeros(sum(e.quantity for e in entries))} units of"
                        f" {symbol} for {acquisition_cost_str}",
                        styles["SubSectionHeading"],
                    )
                )
            elif entry_type == "Spin-off Adjustment":
                spin_off_source = entries[0].spin_off.source
                spin_off_dest = entries[0].spin_off.dest
                story.append(
                    Paragraph(
                        f"{entry_type} {acquisition_count}: {spin_off_source} cost"
                        f" adjusted due to {spin_off_dest} shares",
                        styles["SubSectionHeading"],
                    )
                )
            else:
                story.append(
                    Paragraph(f"{entry_type}: {symbol}", styles["SubSectionHeading"])
                )

            # Add details
            overall_quantity = sum(e.quantity for e in entries)
            overall_fees = round_decimal(sum(e.fees for e in entries), 2)
            if entry_type == "Disposal":
                unit_price = round_decimal(entries[0].amount / entries[0].quantity, 2)
                unit_price_str = f"£{unit_price:,.2f}"
                fee_str = (
                    f", after £{overall_fees:,.2f} fees" if overall_fees > 0 else ""
                )
                story.append(
                    Paragraph(
                        f"Unit price: {unit_price_str}{fee_str}",
                        styles["NormalIndent"],
                    )
                )
                gain_val = round_decimal(sum(e.gain for e in entries), 2)
                if gain_val > 0:
                    gain_str = f"Gain: £{gain_val:,.2f}"
                    total_gain += gain_val
                    story.append(Paragraph(gain_str, styles["NormalIndent"]))
                    story.append(
                        Paragraph(
                            f"Capital gain to date: £{total_gain:,.2f}",
                            styles["NormalIndent"],
                        )
                    )
                else:
                    loss_val = -gain_val
                    loss_str = f"Loss: £{loss_val:,.2f}"
                    total_loss += loss_val
                    story.append(Paragraph(loss_str, styles["NormalIndent"]))
                    story.append(
                        Paragraph(
                            f"Capital loss to date: £{total_loss:,.2f}",
                            styles["NormalIndent"],
                        )
                    )
            elif entry_type == "Acquisition":
                unit_price = (
                    round_decimal(entries[0].allowable_cost / overall_quantity, 2)
                    if overall_quantity > 0
                    else 0
                )
                unit_price_str = f"£{unit_price:,.2f}"
                fee_str = (
                    f", including £{overall_fees:,.2f} fees" if overall_fees > 0 else ""
                )
                story.append(
                    Paragraph(
                        f"Unit price: {unit_price_str}{fee_str}",
                        styles["NormalIndent"],
                    )
                )
            elif entry_type == "Spin-off Adjustment":
                # Additional details can be added here if necessary
                pass
            else:
                # Handle other types if necessary
                pass

            # Create table for entries
            table_data = [
                [
                    Paragraph("Rule Type", styles["TableHeader"]),
                    Paragraph("Quantity", styles["TableHeader"]),
                    Paragraph("Amount (£)", styles["TableHeader"]),
                    Paragraph("Allowable Cost (£)", styles["TableHeader"]),
                    Paragraph("Gain/Loss (£)", styles["TableHeader"]),
                ]
            ]

            # Conditionally add columns for "SECTION 104"
            include_section_104 = any(
                entry.rule_type.name == "SECTION_104" for entry in entries
            )
            if include_section_104:
                table_data[0].extend(
                    [
                        Paragraph("New Quantity", styles["TableHeader"]),
                        Paragraph("New Pool Cost (£)", styles["TableHeader"]),
                    ]
                )

            for entry in entries:
                rule_type = entry.rule_type.name.replace("_", " ")
                quantity = strip_zeros(entry.quantity)
                amount = (
                    f"£{round_decimal(entry.amount, 2):,.2f}" if entry.amount else "-"
                )
                allowable_cost = (
                    f"£{round_decimal(entry.allowable_cost, 2):,.2f}"
                    if entry.allowable_cost
                    else "-"
                )
                gain_loss = (
                    f"£{round_decimal(entry.gain, 2):,.2f}" if entry.gain else "-"
                )
                row = [
                    Paragraph(rule_type, styles["TableCell"]),
                    Paragraph(quantity, styles["TableCell"]),
                    Paragraph(amount, styles["TableCell"]),
                    Paragraph(allowable_cost, styles["TableCell"]),
                    Paragraph(gain_loss, styles["TableCell"]),
                ]

                if include_section_104 and entry.rule_type.name == "SECTION_104":
                    new_quantity = strip_zeros(entry.new_quantity)
                    new_pool_cost = (
                        f"£{round_decimal(entry.new_pool_cost, 2):,.2f}"
                        if entry.new_pool_cost
                        else "-"
                    )
                    row.extend(
                        [
                            Paragraph(new_quantity, styles["TableCell"]),
                            Paragraph(new_pool_cost, styles["TableCell"]),
                        ]
                    )
                elif include_section_104:
                    row.extend(["-", "-"])

                table_data.append(row)

            # Define table style
            table_style = TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.whitesmoke, colors.lightgrey],
                    ),
                ]
            )

            # Create and add table
            report_table = Table(table_data, repeatRows=1, hAlign="LEFT")
            report_table.setStyle(table_style)
            story.append(report_table)
            story.append(Spacer(1, 12))

    # Overall Summary (only once at the end)
    story.append(Spacer(1, 12))
    story.append(Paragraph("Overall Summary", styles["SectionHeading"]))
    story.append(Spacer(1, 12))

    overall_data = [
        ["Number of acquisitions:", acquisition_count],
        ["Number of disposals:", disposal_count],
        ["Total disposal proceeds:", f"£{report.disposal_proceeds:,.2f}"],
        ["Total capital gain before loss:", f"£{total_gain:,.2f}"],
        ["Total capital loss:", f"£{total_loss:,.2f}"],
        ["Total capital gain after loss:", f"£{(total_gain - total_loss):,.2f}"],
    ]

    for label, value in overall_data:
        story.append(Paragraph(f"<b>{label}</b> {value}", styles["NormalIndent"]))

    # Build PDF
    doc.build(story)
