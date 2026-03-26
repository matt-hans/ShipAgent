/**
 * settings-remote remote entry point.
 *
 * Exposes SettingsFlyoutComponent and OnboardingWizardComponent
 * via Native Federation for the shell to load dynamically.
 *
 * PlatformsService is scoped to this remote's providers array
 * so the shell can inject it in a child Injector.
 */

import { SettingsFlyoutComponent } from './settings-flyout/settings-flyout.component';
import { OnboardingWizardComponent } from './onboarding-wizard/onboarding-wizard.component';
import { PlatformsService } from '../services/platforms.service';

export const remoteEntry = {
  component: SettingsFlyoutComponent,
  providers: [PlatformsService],
};

export { SettingsFlyoutComponent, OnboardingWizardComponent, PlatformsService };
