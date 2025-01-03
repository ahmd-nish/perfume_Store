import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import csv
import shopify
import logging
import io
from dotenv import load_dotenv
import os

# --------------------------
# Global Configuration
# --------------------------


load_dotenv()

SHOP_URL = os.getenv("SHOP_URL")
API_VERSION = os.getenv("API_VERSION")
API_TOKEN = os.getenv("API_TOKEN")
# Configure logging
logging.basicConfig(filename='upload_log_with_status.txt', level=logging.INFO)

# ----------------------------------
# Helper Functions for Scraping
# ----------------------------------

def fetch_product_link(gtin):
    """
    Given a GTIN, fetch its product link from the Deloox search API.
    Returns the product page URL if found, otherwise None.
    """
    url = f"https://www.deloox.se/api/search?keyword={gtin}"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) \
                       AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 \
                       Mobile/15E148 Safari/604.1",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        st.warning(f"Error fetching data for GTIN {gtin}: {e}")
        return None

    try:
        soup = BeautifulSoup(response.content, "html.parser")
        product_container = soup.find("div", class_="c-suggest-popular dx_suggest-products")
        if not product_container:
            return None

        product_link = product_container.find("a", class_="c-option suggested-product")
        if not product_link:
            return None

        href = product_link.get("href")
        if href:
            return href
        else:
            return None
    except Exception as e:
        st.warning(f"Error parsing response for GTIN {gtin}: {e}")
        return None


def fetch_product_details(url):
    """
    Given a product URL from Deloox, scrape the product description and image URL.
    Returns (description_text, image_url) or (None, None) on failure.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) \
                       AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 \
                       Mobile/15E148 Safari/604.1",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        st.warning(f"Error fetching product details for URL {url}: {e}")
        return None, None

    try:
        soup = BeautifulSoup(response.content, "html.parser")
        # Extract description
        description_container = soup.find("div", {"id": "dx-description-container"})
        description_text = description_container.get_text(strip=True) if description_container else ""

        # Extract image URL
        image_container = soup.find("div", class_="dx_product-image__container")
        image_url = image_container.find("img").get("src") if image_container and image_container.find("img") else None

        return description_text, image_url
    except Exception as e:
        st.warning(f"Error parsing product details for URL {url}: {e}")
        return None, None

# ----------------------------------------------------
# Shopify-Related Functions
# ----------------------------------------------------

def initialize_shopify_session(shop_url, api_version, api_token):
    """
    Initialize Shopify API session.
    """
    session = shopify.Session(shop_url, api_version, api_token)
    shopify.ShopifyResource.activate_session(session)

def clear_shopify_session():
    """ Clear the Shopify session. """
    shopify.ShopifyResource.clear_session()

def upload_product(name, description, price, image_url, sku, inventory):
    """
    Upload a product to Shopify, including inventory management.
    Returns (success, product_id, error_message).
    """
    try:
        product = shopify.Product()
        product.title = f"Test {name}"  # Example: add "Test" prefix
        product.body_html = description
        product.status = "active"  # Product is active by default

        # Create variant
        variant = shopify.Variant({
            "price": price,
            "sku": sku,
            "inventory_management": "shopify",  # Enable inventory tracking
        })
        product.variants = [variant]

        # Create image
        if image_url:
            image = shopify.Image({"src": image_url})
            product.images = [image]

        # Save product
        success = product.save()
        if not success:
            return False, None, product.errors.full_messages()

        # Set inventory levels
        inventory_item_id = product.variants[0].inventory_item_id
        locations = shopify.Location.find()
        if not locations:
            return False, None, "No locations found for inventory."

        location_id = locations[0].id  # Using the first location
        inventory_level = shopify.InventoryLevel()
        inventory_level.set(
            location_id=location_id,
            inventory_item_id=inventory_item_id,
            available=inventory
        )
        return True, product.id, None
    except Exception as e:
        return False, None, str(e)


def update_product_price(product_id, new_price):
    """
    Updates the price for all variants of a given product ID.
    """
    try:
        product = shopify.Product.find(product_id)
        if not product:
            return f"Product with ID {product_id} not found."

        for variant in product.variants:
            variant.price = str(new_price)
            variant.save()
        success = product.save()
        if success:
            return f"Price updated successfully to {new_price} for product ID {product_id}."
        else:
            return f"Failed to update price for product ID {product_id}: {product.errors.full_messages()}"
    except Exception as e:
        return f"Error: {e}"


def deactivate_product(product_id, status="draft"):
    """
    Sets the product's status to the given status (e.g., 'draft') to deactivate.
    """
    try:
        product = shopify.Product.find(product_id)
        if not product:
            return f"Product with ID {product_id} not found."

        product.status = status
        success = product.save()
        if success:
            return f"Product ID {product_id} has been set to status '{status}'."
        else:
            return f"Failed to update product ID {product_id}: {product.errors.full_messages()}"
    except Exception as e:
        return f"Error while updating product status: {e}"

# ------------------------------------------------
# Streamlit App
# ------------------------------------------------
def main():
    st.title("GTIN Scraper & Shopify Uploader")

    # Sidebar for Shopify credentials (optional if you want user to input them)
    st.sidebar.title("Shopify Credentials")
    shop_url = st.sidebar.text_input("Shop URL", value=SHOP_URL)
    api_version = st.sidebar.text_input("API Version", value=API_VERSION)
    api_token = st.sidebar.text_input("API Token", type="password", value=API_TOKEN)

    # File uploader
    uploaded_file = st.file_uploader("Upload a CSV file with columns: GTIN, Name, Brand, Category, € Price inc. shipping, Inventory", type=["csv"])
    
    if uploaded_file is not None:
        try:
            # Read CSV
            df = pd.read_csv(uploaded_file)
            
            # Basic checks
            required_cols = ["GTIN", "Name", "Brand", "Category", "€ Price inc. shipping", "Inventory"]
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                st.error(f"Missing columns: {missing_cols}")
                return
            
            # Trim dataframe if it's too large for demonstration (optional)
            # df = df.head(10)
            
            st.write("### Original Data Preview")
            st.dataframe(df.head(10))

            # Button to scrape data
            if st.button("Scrape Data from Deloox"):
                scraped_descriptions = []
                scraped_images = []

                for idx, row in df.iterrows():
                    gtin = str(row["GTIN"]).strip()
                    link = fetch_product_link(gtin)
                    if link:
                        desc, img = fetch_product_details(link)
                    else:
                        desc, img = None, None

                    scraped_descriptions.append(desc)
                    scraped_images.append(img)
                    time.sleep(1)  # To be polite to the server

                df["Link"] = [fetch_product_link(str(row["GTIN"])) for _, row in df.iterrows()]
                df["Description"] = scraped_descriptions
                df["Image_URL"] = scraped_images

                # Calculate selling price
                # Example multiplier of 1.40
                df["Selling Price"] = df["€ Price inc. shipping"] * 1.40

                st.write("### Scraped Data Preview")
                st.dataframe(df.head(10))

                # Provide download of the new CSV with scraped data
                csv_buf = io.StringIO()
                df.to_csv(csv_buf, index=False)
                st.download_button(
                    label="Download CSV with Scraped Data",
                    data=csv_buf.getvalue(),
                    file_name="scraped_data.csv",
                    mime="text/csv",
                )

                st.session_state["dataframe"] = df  # Keep in session state

        except Exception as e:
            st.error(f"Error reading or processing file: {e}")

    # Check if we have data in session state to upload
    if "dataframe" in st.session_state:
        st.write("---")
        st.write("## Shopify Upload")

        if st.button("Upload to Shopify"):
            # Initialize Shopify session
            initialize_shopify_session(shop_url, api_version, api_token)
            
            # Prepare columns in DataFrame
            if "Product ID" not in st.session_state["dataframe"].columns:
                st.session_state["dataframe"]["Product ID"] = None
            if "Upload Status" not in st.session_state["dataframe"].columns:
                st.session_state["dataframe"]["Upload Status"] = "Pending"

            for idx, row in st.session_state["dataframe"].iterrows():
                name = row["Name"]
                description = row["Description"] if pd.notnull(row["Description"]) else ""
                selling_price = float(row["Selling Price"]) if not pd.isna(row["Selling Price"]) else 0.0
                image_url = row["Image_URL"] if pd.notnull(row["Image_URL"]) else ""
                sku = str(row["GTIN"])
                inventory = int(row["Inventory"]) if not pd.isna(row["Inventory"]) else 0

                success, product_id, error = upload_product(
                    name, description, selling_price, image_url, sku, inventory
                )
                if success:
                    st.session_state["dataframe"].at[idx, "Product ID"] = product_id
                    st.session_state["dataframe"].at[idx, "Upload Status"] = "Active"
                    logging.info(f"Successfully uploaded: {name}, Product ID: {product_id}")
                else:
                    st.session_state["dataframe"].at[idx, "Upload Status"] = f"Failed: {error}"
                    logging.error(f"Failed to upload product {name}: {error}")

            # Clear Shopify session
            clear_shopify_session()

            # Show final results
            st.write("### Final Uploaded Data")
            st.dataframe(st.session_state["dataframe"].head(10))

            # Provide a download button for the final CSV
            csv_buf = io.StringIO()
            st.session_state["dataframe"].to_csv(csv_buf, index=False)
            st.download_button(
                label="Download Final CSV with Shopify Info",
                data=csv_buf.getvalue(),
                file_name="uploaded_data.csv",
                mime="text/csv",
            )

if __name__ == "__main__":
    main()
