# utils/pdf_generator.py
# -*- coding: utf-8 -*-

import os
import io
import logging
import qrcode
import secrets
from datetime import datetime
import tempfile
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
import pytz

logger = logging.getLogger(__name__)

# Register fonts (using default fonts as fallback)
# For Cyrillic support, you may need to register appropriate fonts
# Example: pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))

class ShipmentPDFGenerator:
    """Generate professional PDF reports for shipments"""
    
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _setup_custom_styles(self):
        """Setup custom paragraph styles for the PDF"""
        # Title style
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#2C3E50'),
            spaceAfter=30,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))
        
        # Header style
        self.styles.add(ParagraphStyle(
            name='CustomHeader',
            parent=self.styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#34495E'),
            spaceAfter=12,
            spaceBefore=12,
            fontName='Helvetica-Bold'
        ))
        
        # Info style
        self.styles.add(ParagraphStyle(
            name='InfoText',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#2C3E50'),
            spaceAfter=6,
            fontName='Helvetica'
        ))
        
        # Small text style
        self.styles.add(ParagraphStyle(
            name='SmallText',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#7F8C8D'),
            fontName='Helvetica'
        ))
    
    def _create_qr_code(self, data, size=150):
        """Generate QR code image"""
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
            
            # Save to BytesIO
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            
            return Image(img_buffer, width=size, height=size)
        except Exception as e:
            logger.error(f"Error generating QR code: {e}")
            return None
    
    def _create_divider(self):
        """Create a horizontal divider line"""
        divider_table = Table([['']], colWidths=[18*cm])
        divider_table.setStyle(TableStyle([
            ('LINEABOVE', (0, 0), (-1, 0), 2, colors.HexColor('#BDC3C7')),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ]))
        return divider_table
    
    def _format_date(self, date_str):
        """Format date string for display"""
        if not date_str:
            return "—"
        return date_str
    
    def generate_shipment_pdf(self, shipment_data, output_path=None):
        """
        Generate PDF for a shipment
        
        Args:
            shipment_data: Dictionary containing shipment information
            output_path: Path to save the PDF (if None, returns BytesIO)
        
        Returns:
            Path to saved PDF or BytesIO object
        """
        try:
            # Create BytesIO buffer if no output path provided
            if output_path is None:
                buffer = io.BytesIO()
                doc = SimpleDocTemplate(buffer, pagesize=A4,
                                       rightMargin=2*cm, leftMargin=2*cm,
                                       topMargin=2*cm, bottomMargin=2*cm)
            else:
                doc = SimpleDocTemplate(output_path, pagesize=A4,
                                       rightMargin=2*cm, leftMargin=2*cm,
                                       topMargin=2*cm, bottomMargin=2*cm)
            
            # Container for the 'Flowable' objects
            elements = []
            
            # Generate report number with date and random component
            report_date = datetime.now(pytz.timezone('Asia/Bishkek')).strftime('%Y%m%d')
            random_num = secrets.token_hex(3).upper()
            report_number = f"RPT-{report_date}-{random_num}"
            
            # Header section with report number and date
            header_data = [
                [Paragraph('<b>SHIPMENT REPORT</b>', self.styles['CustomTitle']), ''],
                [Paragraph(f'<b>Report #:</b> {report_number}', self.styles['InfoText']),
                 Paragraph(f'<b>Generated:</b> {datetime.now(pytz.timezone("Asia/Bishkek")).strftime("%d.%m.%Y %H:%M")}',
                          self.styles['InfoText'])]
            ]
            
            header_table = Table(header_data, colWidths=[12*cm, 6*cm])
            header_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('ALIGN', (1, 1), (1, 1), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ]))
            elements.append(header_table)
            elements.append(self._create_divider())
            
            # Basic Information Section
            elements.append(Paragraph('<b>SHIPMENT INFORMATION</b>', self.styles['CustomHeader']))
            
            basic_info_data = [
                ['Factory:', shipment_data.get('factory_name', '—')],
                ['Destination:', shipment_data.get('warehouse', '—')],
                ['Shipment ID:', shipment_data.get('shipment_id', '—')],
                ['Shipment Date:', self._format_date(shipment_data.get('shipment_date'))],
                ['Estimated Arrival:', self._format_date(shipment_data.get('estimated_arrival'))],
            ]
            
            info_table = Table(basic_info_data, colWidths=[5*cm, 13*cm])
            info_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#34495E')),
                ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#2C3E50')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
            ]))
            elements.append(info_table)
            elements.append(Spacer(1, 0.5*cm))
            elements.append(self._create_divider())
            
            # Summary Section
            total_bags = shipment_data.get('total_bags', 0)
            total_amount = shipment_data.get('total_amount', 0)
            
            elements.append(Paragraph('<b>SUMMARY</b>', self.styles['CustomHeader']))
            
            summary_data = [
                ['Total Bags:', str(total_bags)],
                ['Total Items:', str(total_amount)],
            ]
            
            summary_table = Table(summary_data, colWidths=[5*cm, 13*cm])
            summary_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTNAME', (1, 0), (1, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 12),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#27AE60')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#E8F8F5')),
            ]))
            elements.append(summary_table)
            elements.append(Spacer(1, 0.5*cm))
            elements.append(self._create_divider())
            
            # Bags Details Section
            elements.append(Paragraph('<b>BAG DETAILS</b>', self.styles['CustomHeader']))
            
            bags = shipment_data.get('bags', [])
            if bags:
                # Create table headers
                bag_table_data = [['Bag ID', 'Model', 'Color', 'Quantity', 'Sizes']]
                
                for bag in bags:
                    bag_id = bag.get('bag_id', '—')
                    model = bag.get('model', '—')
                    color = bag.get('color', '—')
                    quantity = bag.get('quantity', 0)
                    
                    # Format sizes
                    sizes_dict = bag.get('sizes', {})
                    sizes_str = ', '.join([f"{size}:{qty}" for size, qty in sizes_dict.items() if qty > 0])
                    if not sizes_str:
                        sizes_str = '—'
                    
                    bag_table_data.append([
                        bag_id,
                        model,
                        color,
                        str(quantity),
                        sizes_str
                    ])
                
                bag_table = Table(bag_table_data, colWidths=[3*cm, 4*cm, 3*cm, 2*cm, 6*cm])
                bag_table.setStyle(TableStyle([
                    # Header style
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495E')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                    
                    # Body style
                    ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 1), (-1, -1), 9),
                    ('ALIGN', (0, 1), (3, -1), 'LEFT'),
                    ('ALIGN', (3, 1), (3, -1), 'CENTER'),
                    ('ALIGN', (4, 1), (4, -1), 'LEFT'),
                    
                    # Grid and padding
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#BDC3C7')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('TOPPADDING', (0, 0), (-1, -1), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ('LEFTPADDING', (0, 0), (-1, -1), 6),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                    
                    # Alternating row colors
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
                ]))
                elements.append(bag_table)
            else:
                elements.append(Paragraph('No bags recorded', self.styles['InfoText']))
            
            elements.append(Spacer(1, 1*cm))
            elements.append(self._create_divider())
            
            # QR Code Section (bottom right)
            qr_url = shipment_data.get('qr_url', f'https://example.com/shipment/{shipment_data.get("shipment_id", "")}')
            qr_code = self._create_qr_code(qr_url, size=100)
            
            if qr_code:
                qr_data = [
                    ['', qr_code],
                    ['', Paragraph('<i>Scan for shipment tracking</i>', self.styles['SmallText'])]
                ]
                qr_table = Table(qr_data, colWidths=[14*cm, 4*cm])
                qr_table.setStyle(TableStyle([
                    ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                    ('VALIGN', (1, 0), (1, -1), 'MIDDLE'),
                ]))
                elements.append(qr_table)
            
            # Add footer
            elements.append(Spacer(1, 0.5*cm))
            footer_text = f'<i>This is an automatically generated report. Report ID: {report_number}</i>'
            elements.append(Paragraph(footer_text, self.styles['SmallText']))
            
            # Build PDF
            doc.build(elements)
            
            if output_path is None:
                buffer.seek(0)
                return buffer
            else:
                logger.info(f"PDF generated successfully: {output_path}")
                return output_path
                
        except Exception as e:
            logger.error(f"Error generating PDF: {e}")
            raise


def create_shipment_pdf(state_data, shipment_id, factory_name="Narselya Factory"):
    """
    Convenience function to create PDF from shipment state data
    
    Args:
        state_data: Dictionary containing shipment state from user_data
        shipment_id: The shipment ID
        factory_name: Name of the factory (default: "Narselya Factory")
    
    Returns:
        BytesIO buffer containing the PDF
    """
    try:
        # Extract data from state
        warehouse = state_data.get('warehouse', '—')
        shipment_date = state_data.get('ship_date', '—')
        estimated_arrival = state_data.get('eta_date', '—')
        models = state_data.get('models', [])
        
        # Calculate totals and prepare bags list
        total_bags = 0
        total_amount = 0
        bags_list = []
        
        for model_item in models:
            model_name = model_item.get('model_name', '—')
            colors = model_item.get('colors', {})
            
            for color, bags in colors.items():
                for bag in bags:
                    bag_id = bag.get('bag_id', '—')
                    sizes = bag.get('sizes', {})
                    bag_qty = sum(int(v or 0) for v in sizes.values())
                    
                    if bag_qty > 0:  # Only include non-empty bags
                        total_bags += 1
                        total_amount += bag_qty
                        
                        bags_list.append({
                            'bag_id': bag_id,
                            'model': model_name,
                            'color': color,
                            'quantity': bag_qty,
                            'sizes': {k: v for k, v in sizes.items() if v > 0}
                        })
        
        # Prepare shipment data for PDF
        shipment_data = {
            'factory_name': factory_name,
            'warehouse': warehouse,
            'shipment_id': shipment_id,
            'shipment_date': shipment_date,
            'estimated_arrival': estimated_arrival,
            'total_bags': total_bags,
            'total_amount': total_amount,
            'bags': bags_list,
            'qr_url': f'https://example.com/shipment/{shipment_id}'  # Update with actual URL when ready
        }
        
        # Generate PDF
        generator = ShipmentPDFGenerator()
        pdf_buffer = generator.generate_shipment_pdf(shipment_data)
        
        return pdf_buffer
        
    except Exception as e:
        logger.error(f"Error creating shipment PDF: {e}")
        raise