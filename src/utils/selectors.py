class RecaptchaSelectors:
    CHECKBOX = "#recaptcha-anchor"
    CHECKBOX_ALTERNATE = "#checkbox, .checkbox"
    AUDIO_BUTTON = "#recaptcha-audio-button, button[title*='audio'], .button-audio, .audio-button"
    PLAY_BUTTON = "button:has-text('PLAY'), .rc-audiochallenge-play-button, .rc-button-default.goog-inline-block, button[title*='play']"
    AUDIO_SOURCE = "audio source"
    AUDIO_ELEMENT = "audio"
    DOWNLOAD_LINK = ".rc-audiochallenge-tdownload-link, a[href*='audio'], a[download]"
    AUDIO_RESPONSE_INPUT = "#audio-response, input[id*='audio'], input[name*='audio'], input[type='text']"
    VERIFY_BUTTON = "#recaptcha-verify-button, .button-submit, button[title*='Verify']"
    CHALLENGE_TITLE = ".rc-imageselect-desc, .rc-imageselect-desc-no-translate, strong"
    TILES = ".rc-imageselect-tile, .rc-image-tile-target"
    CHALLENGE_FRAME = "#recaptcha-challenge, .rc-imageselect"

class GeeTestSelectors:
    SLIDER = ".geetest_slider_button, .geetest_slider_knob"
    CANVAS_BG = ".geetest_canvas_bg canvas, canvas.geetest_canvas_bg"
    CANVAS_SLICE = ".geetest_canvas_slice canvas, canvas.geetest_canvas_slice"

class FunCaptchaSelectors:
    SUBMIT_BUTTON = "button[type='submit'], .button-submit"
    IMAGES = ".fc-image, .fc-image-wrapper img, img[src*='arkose']"
    PROMPT = "#game_header_text, .challenge-instructions, h2"
