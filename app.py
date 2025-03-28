from flask import Flask, render_template, session, redirect, url_for, request, flash
from flask_wtf.csrf import CSRFProtect
import os
from flask_session import Session
from decimal import Decimal, InvalidOperation
from dotenv import load_dotenv
import stripe

# Load environment variables
load_dotenv()

app = Flask(__name__)
csrf = CSRFProtect(app)

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=1800
)

app.config['SESSION_TYPE'] = 'filesystem'  # You can use other session types
app.config['SECRET_KEY'] = 'your_secret_key'  # Change this!
app.secret_key = os.getenv('SECRET_KEY', 'your-fallback-secret-key')
Session(app)

# Configure Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
# Store publishable key to pass to templates
app.config['STRIPE_PUBLISHABLE_KEY'] = os.getenv('STRIPE_PUBLISHABLE_KEY')

STATIC_IMAGE_PATH = 'static/images'

CURRENCIES = {
    'USD': {'symbol': '$', 'rate': 1.0},
    'EUR': {'symbol': '€', 'rate': 0.92},
    'GBP': {'symbol': '£', 'rate': 0.79},
    'JPY': {'symbol': '¥', 'rate': 115.32},
    'AUD': {'symbol': 'A$', 'rate': 1.52},
    'CAD': {'symbol': 'C$', 'rate': 1.36},
    'INR': {'symbol': '₹', 'rate': 82.73}
}

def convert_price(price_usd, currency='USD'):
    """Convert price from USD to selected currency"""
    if currency not in CURRENCIES:
        return f"{price_usd:.2f}", CURRENCIES['USD']['symbol']
    
    converted = price_usd * CURRENCIES[currency]['rate']
    # Special case for JPY which typically doesn't use decimals
    if currency == 'JPY':
        return f"{converted:.0f}", CURRENCIES[currency]['symbol']
    return f"{converted:.2f}", CURRENCIES[currency]['symbol']
def get_plant_details():
    # Dictionary with plant details including prices
    plants = {
        'jade_plant.jpg': {'name': 'Jade Plant', 'price': 9.99},
        'money_plant.jpg': {'name': 'Money Plant', 'price': 4.99},
        'plant.jpg': {'name': 'Peace Lily', 'price': 4.99},
        'plant2.jpg': {'name': 'Snake Plant', 'price': 9.99},
        
    }
    return plants

def get_plant_images():
    images = []
    excluded_images = {'flowers.jpg', 'plant-svgrepo-com.svg', 'customer.jpg', 'doggo.jpg', 'tulips.jpeg'}
    for filename in os.listdir(STATIC_IMAGE_PATH):
        if filename.endswith(('.jpg', '.jpeg', '.png', '.gif')):
            if filename not in excluded_images:
                images.append(filename)
    return images

@app.route('/')
def index():
    plant_details = get_plant_details()
    plant_images = get_plant_images()
    currency = session.get('currency', 'USD')
    
    # Convert prices to selected currency
    converted_details = {}
    for image, details in plant_details.items():
        converted_price, symbol = convert_price(details['price'], currency)
        converted_details[image] = {
            'name': details['name'],
            'price': converted_price,
            'symbol': symbol
        }
    
    return render_template('index.html', 
                         plant_images=plant_images, 
                         plant_details=converted_details,
                         currencies=CURRENCIES,
                         current_currency=currency)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    image = request.form.get('image')
    plant_details = get_plant_details()
    
    if image and image in plant_details:
        if 'cart' not in session:
            session['cart'] = {}
            
        if image not in session['cart']:
            session['cart'][image] = {
                'quantity': 1,
                'name': plant_details[image]['name'],
                'price': str(plant_details[image]['price']),
                'image': image  # Add image reference
            }
        else:
            session['cart'][image]['quantity'] += 1
            
        session.modified = True
        flash('Item added to cart successfully!', 'success')
    else:
        flash('Error adding item to cart', 'error')
        
    return redirect(url_for('cart'))

@app.route('/update_cart', methods=['POST'])
def update_cart():
    image = request.form.get('image')
    action = request.form.get('action')
    
    if 'cart' not in session:
        session['cart'] = {}
    
    if image in session['cart']:
        if action == 'increase':
            session['cart'][image]['quantity'] += 1
        elif action == 'decrease':
            if session['cart'][image]['quantity'] > 1:
                session['cart'][image]['quantity'] -= 1
            else:
                session['cart'].pop(image)
        
        session.modified = True
    
    return redirect(url_for('cart'))

@app.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    image = request.form.get('image')
    if 'cart' in session and image in session['cart']:
        session['cart'].pop(image)
        session.modified = True
    return redirect(url_for('cart'))

@app.route('/cart')
def cart():
    cart_items = session.get('cart', {})
    total = Decimal('0')
    currency = session.get('currency', 'USD')
    
    processed_items = {}
    for image, item in cart_items.items():
        try:
            price_usd = Decimal(str(item['price']))
            quantity = int(item['quantity'])
            
            # Calculate item total in USD first
            item_total_usd = price_usd * quantity
            
            # Convert prices for display only
            converted_price, symbol = convert_price(float(price_usd), currency)
            converted_total, _ = convert_price(float(item_total_usd), currency)
            
            processed_items[image] = {
                'name': item['name'],
                'price': converted_price,
                'symbol': symbol,
                'quantity': quantity,
                'total': converted_total  # Remove f-string formatting
            }
            total += item_total_usd 
        except (ValueError, TypeError) as e:
            print(f"Error processing cart item: {e}")
            continue
    
    final_total, symbol = convert_price(float(total), currency)
    return render_template(
        'cart.html',
        cart_items=processed_items,
        total=final_total,
        currency_symbol=symbol,
        current_currency=currency
    )
@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    cart_items = session.get('cart', {})
    currency = session.get('currency', 'USD')
    if not cart_items:
        flash('Your cart is empty', 'error')
        return redirect(url_for('index'))
    
    total = Decimal('0')
    processed_items = {}
    
    # Process cart items
    for image, item in cart_items.items():
        try:
            # Get original USD price since that's what's stored in cart
            original_price_usd = Decimal(str(item['price']))
            quantity = int(item['quantity'])
            
            # Calculate item total in USD first
            item_total_usd = original_price_usd * quantity
            
            # Convert prices for display
            converted_price, symbol = convert_price(float(original_price_usd), currency)
            converted_total, _ = convert_price(float(item_total_usd), currency)
            
            processed_items[image] = {
                'name': item['name'],
                'price': converted_price,
                'symbol': symbol,
                'quantity': quantity,
                'total': converted_total,
                'price_usd': float(original_price_usd)  # Convert to float for Stripe
            }
            total += item_total_usd
        except (ValueError, TypeError, InvalidOperation) as e:
            print(f"Error processing checkout item: {e}")
            continue
    
    shipping_cost = Decimal('5.00')  # Fixed shipping cost in USD
    shipping_cost_converted, symbol = convert_price(float(shipping_cost), currency)
    
    # Convert final total to selected currency
    converted_total, _ = convert_price(float(total), currency)
    total_with_shipping, _ = convert_price(float(total + shipping_cost), currency)
    
    if request.method == 'POST':
        try:
            # Create Stripe line items using original USD prices
            line_items = []
            for item in processed_items.values():
                line_items.append({
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': item['name'],
                        },
                        'unit_amount': int(float(item['price_usd']) * 100),  # Convert to cents
                    },
                    'quantity': item['quantity'],
                })
            
            # Add shipping as separate line item
            line_items.append({
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Shipping',
                    },
                    'unit_amount': int(shipping_cost * 100),  # Convert to cents
                },
                'quantity': 1,
            })
            
            stripe_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=line_items,
                mode='payment',
                success_url=url_for('success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=url_for('checkout', _external=True),
            )
            return redirect(stripe_session.url, code=303)
        except Exception as e:
            print(f"Error creating Stripe Checkout Session: {e}")
            flash('An error occurred while processing your payment. Please try again.', 'error')
            return redirect(url_for('checkout'))
    
    return render_template(
        'checkout.html',
        cart_items=processed_items,
        subtotal=converted_total,  # Already formatted by convert_price
        shipping_cost=shipping_cost_converted,  # Already formatted by convert_price
        total=total_with_shipping,  # Already formatted by convert_price
        currency_symbol=symbol,
        current_currency=currency
    )

@app.route('/success')
def success():
    return render_template('success.html')

@app.route('/set_currency', methods=['POST'])
def set_currency():
    currency = request.form.get('currency', 'USD')
    if currency in CURRENCIES:
        session['currency'] = currency
    return redirect(request.referrer or url_for('index'))

@app.route('/catalog')
def catalog():
    plant_details = get_plant_details()
    plant_images = get_plant_images()
    currency = session.get('currency', 'USD')
    
    # Convert prices to selected currency
    converted_details = {}
    for image, details in plant_details.items():
        converted_price, symbol = convert_price(details['price'], currency)
        converted_details[image] = {
            'name': details['name'],
            'price': converted_price,
            'symbol': symbol
        }
    
    return render_template('catalog.html', 
                         plant_images=plant_images, 
                         plant_details=converted_details,
                         currencies=CURRENCIES,
                         current_currency=currency)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))