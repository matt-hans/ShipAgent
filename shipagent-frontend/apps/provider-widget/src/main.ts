import { createApplication } from '@angular/platform-browser';
import { createCustomElement } from '@angular/elements';
import { PreviewWidgetComponent } from './app/preview-widget.component';

const tagName = 'shipagent-preview-widget';

createApplication()
  .then((appRef) => {
    if (!customElements.get(tagName)) {
      const element = createCustomElement(PreviewWidgetComponent, {
        injector: appRef.injector,
      });
      customElements.define(tagName, element);
    }
  })
  .catch((err) => console.error(err));
