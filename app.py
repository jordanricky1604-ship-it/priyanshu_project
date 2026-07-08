import streamlit as st
import asyncio
import time
from src.config import get_config
from src.browser import get_browser, close_browser
from src.router import StrategyRouter
import src.solvers

URLS = [
    ("Distorted text", "https://captcha.com/demos/features/captcha-demo.aspx"),
    ("Simple image-text", "https://2captcha.com/demo/normal"),
    ("Audio", "https://captcha.com/audio-captcha-examples.html"),
    ("Image selection", "https://www.google.com/recaptcha/api2/demo"),
    ("hCaptcha", "https://accounts.hcaptcha.com/demo"),
    ("Text question", "https://2captcha.com/demo/text"),
    ("Math", "https://democaptcha.com/demo-form-eng/math-image.html"),
    ("Click objects", "https://2captcha.com/demo/clickcaptcha"),
    ("Rotate image", "https://2captcha.com/demo/rotatecaptcha"),
    ("Slider", "https://www.geetest.com/en/adaptive-captcha-demo"),
    ("Multiple Geetest", "https://gt4.geetest.com/demov4/index-en.html"),
    ("KeyCAPTCHA", "https://2captcha.com/demo/keycaptcha"),
    ("Turnstile", "https://2captcha.com/demo/cloudflare-turnstile"),
    ("reCAPTCHA demo appspot", "https://recaptcha-demo.appspot.com/"),
    ("Custom URL", "")
]

if "history" not in st.session_state:
    st.session_state["history"] = []

st.set_page_config(page_title="CAPTCHA Solver UI", layout="wide")
st.title("🤖 CAPTCHA Solver - Manual UI Tester")
st.markdown("Select a CAPTCHA from the list below and click **Solve**. A visible browser window will open so you can watch the AI solve it in real-time.")

selected_name = st.selectbox("Select CAPTCHA type:", [name for name, url in URLS])

if selected_name == "Custom URL":
    selected_url = st.text_input("Enter your custom CAPTCHA URL:", value="https://example.com")
else:
    selected_url = next(url for name, url in URLS if name == selected_name)
    st.code(selected_url, language="text")

if st.button("🚀 Solve CAPTCHA", type="primary"):
    with st.spinner("Launching browser and starting solver..."):
        async def run_test():
            config = get_config()
            # Force browser to be visible
            config.solver.browser_headless = False  
            
            browser = await get_browser(config.solver)
            router = StrategyRouter(config.solver, browser)
            
            start_time = time.time()
            try:
                # Add a 120s timeout identical to the test script
                solution = await asyncio.wait_for(router.solve(page_url=selected_url), timeout=120.0)
                elapsed = int((time.time() - start_time) * 1000)
                return solution, elapsed
            except Exception as e:
                return e, int((time.time() - start_time) * 1000)
            finally:
                await close_browser()
                
        # Handle async execution within Streamlit safely
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result, elapsed = loop.run_until_complete(run_test())
        
        if isinstance(result, Exception):
            st.error(f"❌ Failed due to exception: {result}")
            st.info(f"Time elapsed before crash/timeout: {elapsed} ms")
            st.session_state["history"].append({"name": selected_name, "status": "Failed", "detail": str(result)})
        elif result.success:
            st.success(f"✅ SUCCESS! Resolved in **{elapsed} ms**")
            
            st.session_state["history"].append({
                "name": selected_name, 
                "status": "Success", 
                "detail": result.token if result.token else "Solved",
                "image": getattr(result, "image_bytes", None)
            })
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("### CAPTCHA Image")
                if getattr(result, "image_bytes", None):
                    st.image(result.image_bytes, use_column_width=True)
                else:
                    st.write("No image captured.")
                    
            with col2:
                st.markdown("### Resolved Captcha Text / Token")
                st.code(result.token if result.token else "N/A", language="text")
                st.json({
                    "captcha_type": result.type.name,
                    "time_ms": elapsed
                })
        else:
            st.error(f"⚠️ FAILED to solve CAPTCHA.")
            st.info(f"Time elapsed: {elapsed} ms")
            st.write(f"**Error Details:** {result.error}")
            st.session_state["history"].append({
                "name": selected_name, 
                "status": "Failed", 
                "detail": result.error,
                "image": getattr(result, "image_bytes", None)
            })

st.markdown("---")
st.markdown("### 📋 Test History")
if not st.session_state["history"]:
    st.write("No CAPTCHAs tested yet.")
else:
    for item in reversed(st.session_state["history"]):
        col_img, col_info = st.columns([1, 4])
        with col_img:
            if item.get("image"):
                st.image(item["image"], use_column_width=True)
            else:
                st.write("No image")
        with col_info:
            if item["status"] == "Success":
                st.success(f"**{item['name']}** — Success captcha : {item['detail']}")
            else:
                st.error(f"**{item['name']}** — Failed: {item['detail']}")
