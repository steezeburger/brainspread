from django.core.management.base import BaseCommand

from ai_chat.models import AIModel, AIProvider


class Command(BaseCommand):
    help = "Populate AIProvider and AIModel tables with available providers and models"

    def handle(self, *args, **options):
        """Create AIProvider and AIModel entries for all available providers and models"""

        # Provider definitions
        providers_data = [
            ("OpenAI", "https://api.openai.com/v1"),
            ("Anthropic", "https://api.anthropic.com"),
            ("Google", "https://generativelanguage.googleapis.com/v1beta"),
        ]

        # Create providers first
        provider_created_count = 0
        for provider_name, base_url in providers_data:
            provider, created = AIProvider.objects.get_or_create(
                name=provider_name, defaults={"base_url": base_url}
            )
            if created:
                provider_created_count += 1
                self.stdout.write(f"Created provider: {provider_name}")

        # Model definitions
        models_data = [
            # OpenAI models
            ("OpenAI", "gpt-4", "GPT-4", "Most capable GPT-4 model"),
            (
                "OpenAI",
                "gpt-4-turbo",
                "GPT-4 Turbo",
                "Faster and more affordable GPT-4",
            ),
            ("OpenAI", "gpt-3.5-turbo", "GPT-3.5 Turbo", "Fast and affordable model"),
            (
                "OpenAI",
                "o1-preview",
                "o1-preview",
                "Reasoning model for complex problems",
            ),
            ("OpenAI", "o1-mini", "o1-mini", "Faster reasoning model"),
            # Anthropic models
            (
                "Anthropic",
                "claude-opus-4-7",
                "Claude Opus 4.7",
                "Most capable Claude model; adaptive thinking, 1M context",
            ),
            (
                "Anthropic",
                "claude-opus-4-6",
                "Claude Opus 4.6",
                "Previous-generation Opus; adaptive thinking, 1M context",
            ),
            (
                "Anthropic",
                "claude-sonnet-4-6",
                "Claude Sonnet 4.6",
                "Best balance of speed and intelligence; 1M context",
            ),
            (
                "Anthropic",
                "claude-haiku-4-5",
                "Claude Haiku 4.5",
                "Fastest and most cost-effective Claude model",
            ),
            # Google models
            (
                "Google",
                "gemini-2.5-pro",
                "Gemini 2.5 Pro",
                "Latest and most capable Gemini model",
            ),
            (
                "Google",
                "gemini-2.5-flash",
                "Gemini 2.5 Flash",
                "Fast version of Gemini 2.5",
            ),
            (
                "Google",
                "gemini-2.0-pro",
                "Gemini 2.0 Pro",
                "Previous generation Gemini Pro",
            ),
            (
                "Google",
                "gemini-2.0-flash",
                "Gemini 2.0 Flash",
                "Previous generation Gemini Flash",
            ),
            ("Google", "gemini-1.5-pro", "Gemini 1.5 Pro", "High-quality Gemini model"),
            ("Google", "gemini-1.5-flash", "Gemini 1.5 Flash", "Fast Gemini model"),
            (
                "Google",
                "gemini-1.5-flash-8b",
                "Gemini 1.5 Flash 8B",
                "Lightweight Gemini model",
            ),
        ]

        created_count = 0
        updated_count = 0

        for provider_name, model_name, display_name, description in models_data:
            try:
                provider = AIProvider.objects.get(name__iexact=provider_name)
            except AIProvider.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(
                        f"Provider '{provider_name}' not found, skipping {model_name}"
                    )
                )
                continue

            ai_model, created = AIModel.objects.get_or_create(
                name=model_name,
                defaults={
                    "provider": provider,
                    "display_name": display_name,
                    "description": description,
                    "is_active": True,
                },
            )

            if created:
                created_count += 1
                self.stdout.write(f"Created model: {model_name}")
            else:
                # Update existing model if needed
                if (
                    ai_model.display_name != display_name
                    or ai_model.description != description
                    or ai_model.provider != provider
                ):
                    ai_model.display_name = display_name
                    ai_model.description = description
                    ai_model.provider = provider
                    ai_model.save()
                    updated_count += 1
                    self.stdout.write(f"Updated model: {model_name}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully processed providers and models. "
                f"Providers created: {provider_created_count}, "
                f"Models created: {created_count}, Models updated: {updated_count}"
            )
        )
