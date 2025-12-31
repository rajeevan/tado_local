import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN, CONF_URL, CONF_PORT, CONF_TOKEN

class TadoLocalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            # You could add a validation check here to ping the API
            return self.async_create_entry(title=f"Tado Local ({user_input[CONF_URL]})", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_URL, default="http://192.168.1.x"): str,
                vol.Required(CONF_PORT, default=8000): int,
                vol.Required(CONF_TOKEN): str,
            }),
            errors=errors,
        )