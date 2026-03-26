/**
 * ShipAgentLogoComponent — The ShipAgent application logo.
 *
 * A minimalist cardboard shipping box with packing tape.
 * Port of ShipAgentLogo.tsx and ShipAgentIcon from the React frontend.
 */

import {
  ChangeDetectionStrategy,
  Component,
  Input,
  ViewEncapsulation,
} from '@angular/core';

@Component({
  selector: 'sa-shipagent-logo',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `
    <svg [attr.viewBox]="'0 0 48 48'" fill="none" [attr.class]="class">
      <g>
        <!-- Main box front face -->
        <rect
          x="6"
          y="16"
          width="28"
          height="22"
          rx="1.5"
          [attr.fill]="primaryColor"
          fill-opacity="0.15"
          [attr.stroke]="primaryColor"
          stroke-width="2"
        />
        <!-- Box right side (3D depth) -->
        <path
          d="M34 16L42 12V32L34 38V16Z"
          [attr.fill]="primaryColor"
          fill-opacity="0.08"
          [attr.stroke]="primaryColor"
          stroke-width="2"
          stroke-linejoin="round"
        />
        <!-- Box top face -->
        <path
          d="M6 16L14 10H34L42 12L34 16H6Z"
          [attr.fill]="primaryColor"
          fill-opacity="0.1"
          [attr.stroke]="primaryColor"
          stroke-width="2"
          stroke-linejoin="round"
        />
        <!-- Packing tape - center vertical strip on top -->
        <path
          d="M20 10V16"
          [attr.stroke]="primaryColor"
          stroke-width="4"
          stroke-linecap="butt"
          opacity="0.35"
        />
        <!-- Packing tape - continues down front -->
        <path
          d="M20 16V38"
          [attr.stroke]="primaryColor"
          stroke-width="4"
          stroke-linecap="butt"
          opacity="0.25"
        />
        <!-- Box flap seam lines on top -->
        <path
          d="M14 10L20 13L34 10"
          [attr.stroke]="primaryColor"
          stroke-width="1.5"
          stroke-linecap="round"
          opacity="0.4"
        />
      </g>
    </svg>
  `,
})
export class ShipAgentLogoComponent {
  /** CSS class to apply to the SVG element. */
  @Input() class = '';
  /** Primary color for the package (default: amber). */
  @Input() primaryColor = '#f59e0b';
}

@Component({
  selector: 'sa-shipagent-icon',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `
    <svg viewBox="0 0 24 24" fill="none" [attr.class]="class">
      <!-- Simple parcel box -->
      <rect
        x="3"
        y="7"
        width="14"
        height="12"
        rx="1"
        fill="currentColor"
        fill-opacity="0.15"
        stroke="currentColor"
        stroke-width="1.5"
      />
      <!-- 3D side -->
      <path
        d="M17 7L21 5V15L17 19V7Z"
        fill="currentColor"
        fill-opacity="0.08"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linejoin="round"
      />
      <!-- Top flap -->
      <path
        d="M3 7L10 4L17 7"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
      <path d="M17 7L21 5" stroke="currentColor" stroke-width="1.5" />
      <!-- Tape -->
      <line x1="10" y1="4" x2="10" y2="7" stroke="currentColor" stroke-width="2" opacity="0.5" />
    </svg>
  `,
})
export class ShipAgentIconComponent {
  /** CSS class to apply to the SVG element. */
  @Input() class = '';
}
