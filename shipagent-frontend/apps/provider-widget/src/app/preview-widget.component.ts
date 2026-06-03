import { Component, input } from '@angular/core';

@Component({
  selector: 'shipagent-preview-widget',
  standalone: true,
  template: `
    <section class="widget">
      <h1>Shipment Preview</h1>
      <p>{{ summary() }}</p>
    </section>
  `,
})
export class PreviewWidgetComponent {
  summary = input('Waiting for preview data');
}
