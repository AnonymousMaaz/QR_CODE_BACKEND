from flask import Flask, request, jsonify, send_file, render_template
import qrcode
from io import BytesIO
import base64
from flask_cors import CORS
import re
from PIL import Image, ImageDraw
import qrcode.image.svg
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static')
CORS(app, resources={r"/*": {"origins": "*"}})

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/generate-qr', methods=['POST', 'OPTIONS'])
def generate_qr():
    # Handle preflight requests
    if request.method == 'OPTIONS':
        return jsonify(success=True)
    
    try:
        # Check if the request comes from form (Content-Type: application/x-www-form-urlencoded)
        if request.content_type == 'application/x-www-form-urlencoded':
            data = json.loads(request.form.get('requestData', '{}'))
        else:
            # Regular JSON request
            data = request.json
        # Get data from request
        logger.debug(f"Received QR generation request with style: {data.get('style')}")
        
        qr_data = data.get('data', '')
        qr_size = int(data.get('size', 300))
        qr_color = data.get('color', '000000')
        qr_bg_color = data.get('bgColor', 'FFFFFF')
        qr_style = data.get('style', 'standard')
        logo_data = data.get('logo', None)
        
        # Convert hex colors to RGB tuples
        fill_color = tuple(int(qr_color[i:i+2], 16) for i in (0, 2, 4))
        back_color = tuple(int(qr_bg_color[i:i+2], 16) for i in (0, 2, 4))
        
        # Create QR code instance with different settings based on style
        error_correction = qrcode.constants.ERROR_CORRECT_H  # Always use high error correction for logo support
        
        # For rounded style, we need SVG
        if qr_style == 'rounded':
            logger.debug("Using SVG for rounded style")
            # Use SVG factory with specific configuration for rounded corners
            factory = qrcode.image.svg.SvgPathImage
            qr = qrcode.QRCode(
                version=None,
                error_correction=error_correction,
                box_size=10,
                border=4,
                image_factory=factory
            )
            qr.add_data(qr_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color='black', back_color='white')
            
            # Modify SVG to have rounded corners
            svg_str = img.to_string().decode('utf-8')
            # Add rounded corners to the SVG paths
            svg_str = svg_str.replace('<path d=', '<path stroke-linejoin="round" stroke-linecap="round" d=')
            
            # Save as SVG
            buffer = BytesIO()
            buffer.write(svg_str.encode('utf-8'))
            buffer.seek(0)
            img_format = "SVG"
            
            # Convert to base64 for API response
            img_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
            
            return jsonify({
                'success': True,
                'image': f'data:image/svg+xml;base64,{img_str}'
            })
        else:
            # Use PIL for other styles
            box_size = max(1, qr_size // 25)  # Adjusted box size for better visibility
            border = 4 if qr_style == 'standard' else 2
            
            qr = qrcode.QRCode(
                version=None,
                error_correction=error_correction,
                box_size=box_size,
                border=border
            )
            
            qr.add_data(qr_data)
            qr.make(fit=True)
            
            # Create base QR code image
            img = qr.make_image(fill_color=fill_color, back_color=back_color)
            img = img.convert('RGBA')
            
            # Apply dot style
            if qr_style == 'dot':
                try:
                    logger.debug("Applying dot style")
                    
                    # Get QR code matrix
                    qr_matrix = qr.get_matrix()
                    
                    # Get actual image dimensions
                    qr_width, qr_height = img.size
                    
                    # Create a new transparent image
                    dot_img = Image.new('RGBA', (qr_width, qr_height), (0, 0, 0, 0))
                    draw = ImageDraw.Draw(dot_img)
                    
                    # Calculate size of each module
                    modules_count = len(qr_matrix)
                    module_size = min(qr_width, qr_height) / (modules_count + 2 * border)  # Account for border
                    
                    # Fill the background
                    bg_img = Image.new('RGBA', (qr_width, qr_height), back_color + (255,))
                    
                    # Draw each module as a circle
                    for y, row in enumerate(qr_matrix):
                        for x, cell in enumerate(row):
                            if cell:
                                # Calculate position with border offset
                                center_x = (x + border) * module_size + module_size / 2
                                center_y = (y + border) * module_size + module_size / 2
                                
                                # Circle radius (slightly smaller than half module size)
                                radius = module_size * 0.4
                                
                                # Draw circle
                                draw.ellipse(
                                    (center_x - radius, center_y - radius, 
                                     center_x + radius, center_y + radius),
                                    fill=fill_color + (255,)  # Add alpha channel
                                )
                    
                    # Create final image by compositing dots over background
                    img = Image.alpha_composite(bg_img, dot_img)
                    logger.debug("Dot style applied successfully")
                except Exception as e:
                    logger.error(f"Error applying dot style: {e}")
            
            # Add logo if provided
            if logo_data and "data:image" in logo_data:
                try:
                    logger.debug("Processing logo")
                    # Extract base64 data
                    logo_base64 = re.search(r'base64,(.+)', logo_data).group(1)
                    logo_bytes = base64.b64decode(logo_base64)
                    logo_img = Image.open(BytesIO(logo_bytes))
                    
                    # Resize logo to be about 20% of the QR code
                    logo_size = min(qr_width, qr_height) // 5
                    logo_img = logo_img.resize((logo_size, logo_size), Image.LANCZOS)
                    
                    # Ensure logo has alpha channel
                    if logo_img.mode != 'RGBA':
                        logo_img = logo_img.convert('RGBA')
                    
                    # Create white background for logo
                    logo_bg = Image.new('RGBA', logo_img.size, (255, 255, 255, 255))
                    
                    # Calculate position to center logo
                    pos_x = (qr_width - logo_size) // 2
                    pos_y = (qr_height - logo_size) // 2
                    
                    # Create a copy of the QR image to avoid modifying the original
                    qr_with_logo = img.copy()
                    
                    # Paste white background then logo
                    qr_with_logo.paste(logo_bg, (pos_x, pos_y), logo_bg)
                    qr_with_logo.paste(logo_img, (pos_x, pos_y), logo_img)
                    
                    img = qr_with_logo
                    logger.debug("Logo added successfully")
                except Exception as e:
                    logger.error(f"Error adding logo: {e}")
            
            # Save image to buffer
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)
            
            # Convert to base64
            img_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
            
            return jsonify({
                'success': True,
                'image': f'data:image/png;base64,{img_str}'
            })
    
    except Exception as e:
        logger.error(f"Error generating QR code: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/download-qr', methods=['POST', 'OPTIONS'])
def download_qr():
    # Handle preflight requests
    if request.method == 'OPTIONS':
        return jsonify(success=True)
    
    try:
        # This route provides a downloadable file
        data = request.json
        
        qr_data = data.get('data', '')
        qr_size = int(data.get('size', 300))
        qr_color = data.get('color', '000000')
        qr_bg_color = data.get('bgColor', 'FFFFFF')
        qr_style = data.get('style', 'standard')
        logo_data = data.get('logo', None)
        output_format = data.get('format', 'png').lower()
        
        # Convert hex colors to RGB tuples
        fill_color = tuple(int(qr_color[i:i+2], 16) for i in (0, 2, 4))
        back_color = tuple(int(qr_bg_color[i:i+2], 16) for i in (0, 2, 4))
        
        # For rounded style or SVG format, use SVG output
        if output_format == 'svg' or qr_style == 'rounded':
            factory = qrcode.image.svg.SvgPathImage
            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=10,
                border=4,
                image_factory=factory
            )
            qr.add_data(qr_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color='black', back_color='white')
            
            # Modify SVG for rounded style
            if qr_style == 'rounded':
                svg_str = img.to_string().decode('utf-8')
                svg_str = svg_str.replace('<path d=', '<path stroke-linejoin="round" stroke-linecap="round" d=')
                
                buffer = BytesIO()
                buffer.write(svg_str.encode('utf-8'))
                buffer.seek(0)
            else:
                buffer = BytesIO()
                img.save(buffer)
                buffer.seek(0)
            
            mimetype = 'image/svg+xml'
            download_name = 'beautiful_qrcode.svg'
        else:
            # Use PIL for other styles
            box_size = max(1, qr_size // 25)
            border = 4 if qr_style == 'standard' else 2
            
            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=box_size,
                border=border
            )
            qr.add_data(qr_data)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color=fill_color, back_color=back_color)
            img = img.convert('RGBA')
            
            # Apply dot style
            if qr_style == 'dot':
                try:
                    qr_matrix = qr.get_matrix()
                    qr_width, qr_height = img.size
                    
                    dot_img = Image.new('RGBA', (qr_width, qr_height), (0, 0, 0, 0))
                    draw = ImageDraw.Draw(dot_img)
                    
                    modules_count = len(qr_matrix)
                    module_size = min(qr_width, qr_height) / (modules_count + 2 * border)
                    
                    bg_img = Image.new('RGBA', (qr_width, qr_height), back_color + (255,))
                    
                    for y, row in enumerate(qr_matrix):
                        for x, cell in enumerate(row):
                            if cell:
                                center_x = (x + border) * module_size + module_size / 2
                                center_y = (y + border) * module_size + module_size / 2
                                radius = module_size * 0.4
                                
                                draw.ellipse(
                                    (center_x - radius, center_y - radius, 
                                     center_x + radius, center_y + radius),
                                    fill=fill_color + (255,)
                                )
                    
                    img = Image.alpha_composite(bg_img, dot_img)
                except Exception as e:
                    logger.error(f"Error applying dot style: {e}")
            
            # Add logo if provided
            if logo_data and "data:image" in logo_data:
                try:
                    logo_base64 = re.search(r'base64,(.+)', logo_data).group(1)
                    logo_bytes = base64.b64decode(logo_base64)
                    logo_img = Image.open(BytesIO(logo_bytes))
                    
                    qr_width, qr_height = img.size
                    logo_size = min(qr_width, qr_height) // 5
                    logo_img = logo_img.resize((logo_size, logo_size), Image.LANCZOS)
                    
                    if logo_img.mode != 'RGBA':
                        logo_img = logo_img.convert('RGBA')
                    
                    logo_bg = Image.new('RGBA', logo_img.size, (255, 255, 255, 255))
                    
                    pos_x = (qr_width - logo_size) // 2
                    pos_y = (qr_height - logo_size) // 2
                    
                    qr_with_logo = img.copy()
                    qr_with_logo.paste(logo_bg, (pos_x, pos_y), logo_bg)
                    qr_with_logo.paste(logo_img, (pos_x, pos_y), logo_img)
                    
                    img = qr_with_logo
                except Exception as e:
                    logger.error(f"Error adding logo: {e}")
            
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)
            
            mimetype = 'image/png'
            download_name = 'beautiful_qrcode.png'
        
        return send_file(buffer, mimetype=mimetype, download_name=download_name, as_attachment=True)
    except Exception as e:
        logger.error(f"Error downloading QR code: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
