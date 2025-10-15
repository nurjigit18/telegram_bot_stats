# utils/pdf_generator.py
# -*- coding: utf-8 -*-

import io
import logging
import secrets
from datetime import datetime

import qrcode
import pytz

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

# Register fonts (paths must exist)
pdfmetrics.registerFont(TTFont('DejaVuSans',       'fonts/DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', 'fonts/DejaVuSans-Bold.ttf'))


class ShipmentPDFGenerator:
    """Generate PDF reports for shipments."""

    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    # -------------------------- styles ---------------------------------
    def _setup_custom_styles(self):
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#2C3E50'),
            spaceAfter=4,
            alignment=TA_CENTER,
            fontName='DejaVuSans-Bold'
        ))
        self.styles.add(ParagraphStyle(
            name='CustomHeader',
            parent=self.styles['Heading2'],
            fontSize=10,
            textColor=colors.HexColor('#34495E'),
            spaceAfter=6,
            spaceBefore=6,
            fontName='DejaVuSans-Bold'
        ))
        self.styles.add(ParagraphStyle(
            name='InfoText',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#2C3E50'),
            spaceAfter=4,
            fontName='DejaVuSans'
        ))
        self.styles.add(ParagraphStyle(
            name='SmallText',
            parent=self.styles['Normal'],
            fontSize=6,
            textColor=colors.HexColor('#7F8C8D'),
            fontName='DejaVuSans'
        ))

    # -------------------------- helpers --------------------------------
    def _create_qr_code(self, data, size=300):
        """Return QR code as a Flowable Image."""
        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(data)
            qr.make(fit=True)

            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)
            return Image(buf, width=size, height=size)
        except Exception as e:
            logger.error(f"Error generating QR code: {e}")
            return None

    def _create_divider(self):
        """Horizontal divider spanning content width (~17 cm with 2+2 cm margins)."""
        divider_table = Table([['']], colWidths=[17 * cm])
        divider_table.setStyle(TableStyle([
            ('LINEABOVE', (0, 0), (-1, 0), 2, colors.HexColor('#BDC3C7')),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        return divider_table

    def _format_date(self, date_str):
        return date_str or "—"

    # --------------------------- main ----------------------------------
    def generate_shipment_pdf(self, shipment_data, output_path=None):
        """
        Build PDF and return BytesIO (if output_path is None) or file path.
        """
        try:
            # Document
            if output_path is None:
                buffer = io.BytesIO()
                doc = SimpleDocTemplate(
                    buffer, pagesize=A4,
                    rightMargin=2*cm, leftMargin=2*cm,
                    topMargin=2*cm, bottomMargin=2*cm
                )
            else:
                doc = SimpleDocTemplate(
                    output_path, pagesize=A4,
                    rightMargin=2*cm, leftMargin=2*cm,
                    topMargin=2*cm, bottomMargin=2*cm
                )

            elements = []

            # Report meta
            now_bishkek = datetime.now(pytz.timezone('Asia/Bishkek'))
            report_date = now_bishkek.strftime('%Y%m%d')
            random_num = secrets.token_hex(3).upper()
            report_number = f"RPT-{report_date}-{random_num}"

            # Header
            header_data = [
                [Paragraph('<b>ОТЧЕТ ОБ ОТПРАВКЕ</b>', self.styles['CustomTitle']), ''],
                [
                    Paragraph(f'<b>Номер отчета #:</b> {report_number}', self.styles['InfoText']),
                    Paragraph(f'<b>Дата:</b> {now_bishkek.strftime("%d.%m.%Y %H:%M")}', self.styles['InfoText'])
                ]
            ]
            header_table = Table(header_data, colWidths=[8.5*cm, 8.5*cm])
            header_table.setStyle(TableStyle([
                ('SPAN', (0, 0), (1, 0)),              # Merge title across both columns
                ('ALIGN', (0, 0), (1, 0), 'CENTER'),   # Title centered
                ('ALIGN', (0, 1), (0, 1), 'LEFT'),     # Report number left
                ('ALIGN', (1, 1), (1, 1), 'RIGHT'),    # Date right
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 10),  # Add padding below title
            ]))
            elements.append(header_table)
            elements.append(self._create_divider())

            # =================== LEFT: Shipment Info ======================
            basic_info_data = [
                ['Поставщик:',     shipment_data.get('factory_name', '—')],
                ['Склад:',         shipment_data.get('warehouse', '—')],
                ['ID отправки:',   shipment_data.get('shipment_id', '—')],
                ['Дата отправки:', self._format_date(shipment_data.get('shipment_date'))],
            ]

            info_header = Paragraph('<b>ИНФОРМАЦИЯ ОБ ОТПРАВКЕ</b>', self.styles['CustomHeader'])
            # Left column width: 10.5 cm -> internal columns 3.5 + 7.0
            info_table = Table(basic_info_data, colWidths=[3.5*cm, 7.0*cm])
            info_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (0, -1), 'DejaVuSans-Bold'),
                ('FONTNAME', (1, 0), (1, -1), 'DejaVuSans'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#34495E')),
                ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#2C3E50')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
            ]))
            left_block = [info_header, info_table]

            # =================== RIGHT: Summaries =========================
            total_bags = shipment_data.get('total_bags', 0)
            total_amount = shipment_data.get('total_amount', 0)

            summary_header = Paragraph('<b>СВОДКИ</b>', self.styles['CustomHeader'])
            # Right column width: 6.5 cm -> internal columns 4.2 + 2.3
            summary_table = Table(
                [['Количество пакетов:', str(total_bags)],
                 ['Общее количество (ед):', str(total_amount)]],
                colWidths=[4.2*cm, 2.3*cm]
            )
            summary_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (0, -1), 'DejaVuSans-Bold'),
                ('FONTNAME', (1, 0), (1, -1), 'DejaVuSans-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#27AE60')),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#E8F8F5')),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ]))
            right_block = [summary_header, summary_table]

            # =================== Side-by-side container ===================
            # Total inner width 17 cm: 10.5 + 6.5
            side_by_side = Table([[left_block, right_block]], colWidths=[10.5*cm, 6.5*cm])
            side_by_side.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            elements.append(side_by_side)
            elements.append(Spacer(1, 0.5 * cm))
            elements.append(self._create_divider())

            # =================== Bags table ===============================
            elements.append(Paragraph('<b>ИНФОРМАЦИЯ О ПАКЕТАХ</b>', self.styles['CustomHeader']))

            bags = shipment_data.get('bags', [])
            if bags:
                bag_table_data = [['ID пакета', 'Модель', 'Цвет', 'Количество', 'Размеры']]
                for bag in bags:
                    bag_id = bag.get('bag_id', '—')
                    model = bag.get('model', '—')
                    color = bag.get('color', '—')
                    quantity = bag.get('quantity', 0)
                    sizes_dict = bag.get('sizes', {})
                    sizes_str = ', '.join([f"{size}:{qty}" for size, qty in sizes_dict.items() if qty > 0]) or '—'
                    bag_table_data.append([bag_id, model, color, str(quantity), sizes_str])

                bag_table = Table(bag_table_data, colWidths=[3*cm, 4*cm, 3*cm, 2*cm, 5*cm])  # 17 cm
                bag_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495E')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('FONTNAME', (0, 0), (-1, 0), 'DejaVuSans-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 8),
                    ('ALIGN', (0, 0), (-1, 0), 'CENTER'),

                    ('FONTNAME', (0, 1), (-1, -1), 'DejaVuSans'),
                    ('FONTSIZE', (0, 1), (-1, -1), 7),
                    ('ALIGN', (0, 1), (2, -1), 'LEFT'),
                    ('ALIGN', (3, 1), (3, -1), 'CENTER'),
                    ('ALIGN', (4, 1), (4, -1), 'LEFT'),

                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#BDC3C7')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('TOPPADDING', (0, 0), (-1, -1), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ('LEFTPADDING', (0, 0), (-1, -1), 6),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 6),

                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
                ]))
                elements.append(bag_table)
            else:
                elements.append(Paragraph('Нет данных по пакетам', self.styles['InfoText']))

            elements.append(Spacer(1, 1 * cm))
            elements.append(self._create_divider())

            # =================== QR section (bottom-right) ================
            qr_url = shipment_data.get('qr_url', f'https://example.com/shipment/{shipment_data.get("shipment_id", "")}')
            qr_code = self._create_qr_code(qr_url, size=100)
            if qr_code:
                qr_data = [
                    ['', qr_code],
                    ['', Paragraph('<i>Отсканируйте при получении или отправке товара</i>', self.styles['SmallText'])]
                ]
                # 13 + 4 = 17 cm
                qr_table = Table(qr_data, colWidths=[13*cm, 4*cm])
                qr_table.setStyle(TableStyle([
                    ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                    ('VALIGN', (1, 0), (1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ]))
                elements.append(qr_table)

            # Footer
            elements.append(Spacer(1, 0.5 * cm))
            footer_text = f'<i>Автоматически сгенерированный отчет. Номер отчета: {report_number}</i>'
            elements.append(Paragraph(footer_text, self.styles['SmallText']))

            # Build
            doc.build(elements)

            if output_path is None:
                buffer.seek(0)
                return buffer
            logger.info(f"PDF generated successfully: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Error generating PDF: {e}")
            raise


def create_shipment_pdf(state_data, shipment_id, factory_name="Factory"):
    """
    Build shipment PDF from bot state structure.
    Returns BytesIO buffer.
    """
    try:
        warehouse = state_data.get('warehouse', '—')
        shipment_date = state_data.get('ship_date', '—')
        estimated_arrival = state_data.get('eta_date', '—')
        models = state_data.get('models', [])

        total_bags = 0
        total_amount = 0
        bags_list = []

        for model_item in models:
            model_name = model_item.get('model_name', '—')
            colors_map = model_item.get('colors', {})
            for color, bags in colors_map.items():
                for bag in bags:
                    bag_id = bag.get('bag_id', '—')
                    sizes = bag.get('sizes', {}) or {}
                    bag_qty = sum(int(v or 0) for v in sizes.values())
                    if bag_qty > 0:
                        total_bags += 1
                        total_amount += bag_qty
                        bags_list.append({
                            'bag_id': bag_id,
                            'model': model_name,
                            'color': color,
                            'quantity': bag_qty,
                            'sizes': {k: v for k, v in sizes.items() if (v or 0) > 0}
                        })

        shipment_data = {
            'factory_name': factory_name,
            'warehouse': warehouse,
            'shipment_id': shipment_id,
            'shipment_date': shipment_date,
            'estimated_arrival': estimated_arrival,
            'total_bags': total_bags,
            'total_amount': total_amount,
            'bags': bags_list,
            'qr_url': f'https://example.com/shipment/{shipment_id}',
        }

        generator = ShipmentPDFGenerator()
        return generator.generate_shipment_pdf(shipment_data)

    except Exception as e:
        logger.error(f"Error creating shipment PDF: {e}")
        raise
