/**
 * Test Order Generator
 *
 * Generates realistic Shopify test orders using @faker-js/faker.
 * - Seeded randomization for reproducibility
 * - Configurable distribution of order statuses
 * - 1-5 line items per order with varied products/weights
 * - All orders tagged with 'shipagent-test' for easy cleanup
 */

import { faker } from "@faker-js/faker";
import type {
  ShopifyOrderPayload,
  ShopifyAddress,
  ShopifyLineItem,
  FinancialStatus,
  FulfillmentStatus,
} from "./types.js";
import { getWeightedRandomAddress, US_STATE_NAMES } from "./address-database.js";

/**
 * Test tag applied to all generated orders
 */
export const TEST_ORDER_TAG = "shipagent-test";

/**
 * Product catalog for line items
 */
const PRODUCTS = [
  { title: "Wireless Bluetooth Headphones", price: "79.99", gramsBase: 300 },
  { title: "USB-C Charging Cable 6ft", price: "12.99", gramsBase: 50 },
  { title: "Portable Power Bank 10000mAh", price: "34.99", gramsBase: 250 },
  { title: "Laptop Stand Adjustable", price: "45.99", gramsBase: 800 },
  { title: "Mechanical Keyboard RGB", price: "89.99", gramsBase: 950 },
  { title: "Wireless Mouse Ergonomic", price: "29.99", gramsBase: 120 },
  { title: "Webcam 1080p HD", price: "59.99", gramsBase: 150 },
  { title: "USB Hub 7-Port", price: "24.99", gramsBase: 180 },
  { title: "Monitor Stand Riser", price: "39.99", gramsBase: 1200 },
  { title: "Desk Organizer Set", price: "19.99", gramsBase: 400 },
  { title: "LED Desk Lamp", price: "32.99", gramsBase: 600 },
  { title: "Noise Canceling Earbuds", price: "129.99", gramsBase: 80 },
  { title: "Smart Watch Band", price: "18.99", gramsBase: 30 },
  { title: "Phone Case Premium", price: "24.99", gramsBase: 45 },
  { title: "Screen Protector 3-Pack", price: "14.99", gramsBase: 20 },
  { title: "Wireless Charger Pad", price: "22.99", gramsBase: 150 },
  { title: "HDMI Cable 10ft", price: "16.99", gramsBase: 200 },
  { title: "External SSD 500GB", price: "79.99", gramsBase: 100 },
  { title: "Memory Card 128GB", price: "24.99", gramsBase: 10 },
  { title: "Camera Tripod Mini", price: "28.99", gramsBase: 350 },
];

/**
 * Financial status distribution
 * - paid: 85%
 * - pending: 10%
 * - refunded: 5%
 */
const FINANCIAL_STATUS_DISTRIBUTION: { status: FinancialStatus; weight: number }[] = [
  { status: "paid", weight: 0.85 },
  { status: "pending", weight: 0.10 },
  { status: "refunded", weight: 0.05 },
];

/**
 * Fulfillment status distribution
 * - unfulfilled (null): 70%
 * - partial: 10%
 * - fulfilled: 20%
 */
const FULFILLMENT_STATUS_DISTRIBUTION: { status: FulfillmentStatus; weight: number }[] = [
  { status: null, weight: 0.70 },
  { status: "partial", weight: 0.10 },
  { status: "fulfilled", weight: 0.20 },
];

/**
 * Order generator configuration
 */
export interface OrderGeneratorConfig {
  /** Random seed for reproducibility */
  seed: number;
  /** Starting index for order numbering */
  startIndex: number;
}

/**
 * Test Order Generator
 *
 * Usage:
 * ```typescript
 * const generator = new OrderGenerator({ seed: 12345, startIndex: 0 });
 * const order = generator.generateOrder(0);
 * ```
 */
export class OrderGenerator {
  private readonly fakerInstance: typeof faker;
  private readonly random: () => number;

  constructor(private readonly config: OrderGeneratorConfig) {
    // Create seeded faker instance
    this.fakerInstance = faker;
    this.fakerInstance.seed(config.seed);

    // Create seeded random function
    this.random = () => this.fakerInstance.number.float({ min: 0, max: 1 });
  }

  /**
   * Generates a single test order
   *
   * @param index - Order index (used for unique email)
   * @returns Shopify order creation payload
   */
  generateOrder(index: number): ShopifyOrderPayload {
    const absoluteIndex = this.config.startIndex + index;

    // Generate customer info
    const firstName = this.fakerInstance.person.firstName();
    const lastName = this.fakerInstance.person.lastName();
    const email = `test-${absoluteIndex}@shipagent-test.example.com`;

    // Generate address
    const address = this.generateAddress(firstName, lastName);

    // Generate line items (1-5 items)
    const itemCount = this.fakerInstance.number.int({ min: 1, max: 5 });
    const lineItems = this.generateLineItems(itemCount);

    // Generate statuses
    const financialStatus = this.selectWeighted(FINANCIAL_STATUS_DISTRIBUTION);
    const fulfillmentStatus = this.selectWeighted(FULFILLMENT_STATUS_DISTRIBUTION);

    // Generate created_at within past 30 days
    const createdAt = this.generatePastDate(30);

    // Generate optional note
    const note = this.random() < 0.2
      ? this.fakerInstance.lorem.sentence()
      : undefined;

    return {
      order: {
        email,
        financial_status: financialStatus,
        fulfillment_status: fulfillmentStatus,
        send_receipt: false,
        send_fulfillment_receipt: false,
        line_items: lineItems,
        shipping_address: address,
        billing_address: address,
        created_at: createdAt,
        tags: TEST_ORDER_TAG,
        note,
      },
    };
  }

  /**
   * Generates a batch of orders
   *
   * @param count - Number of orders to generate
   * @returns Array of order payloads
   */
  generateBatch(count: number): ShopifyOrderPayload[] {
    const orders: ShopifyOrderPayload[] = [];
    for (let i = 0; i < count; i++) {
      orders.push(this.generateOrder(i));
    }
    return orders;
  }

  /**
   * Gets order statistics for a batch (for preview)
   *
   * @param count - Number of orders to analyze
   * @returns Distribution statistics
   */
  getDistributionStats(count: number): {
    states: Record<string, number>;
    financial: Record<string, number>;
    fulfillment: Record<string, number>;
  } {
    // Save current seed state
    const savedSeed = this.config.seed;
    this.fakerInstance.seed(savedSeed);

    const states: Record<string, number> = {};
    const financial: Record<string, number> = {};
    const fulfillment: Record<string, number> = {};

    for (let i = 0; i < count; i++) {
      const order = this.generateOrder(i);
      const addr = order.order.shipping_address;

      // Count state
      states[addr.province_code] = (states[addr.province_code] || 0) + 1;

      // Count financial status
      financial[order.order.financial_status] =
        (financial[order.order.financial_status] || 0) + 1;

      // Count fulfillment status
      const fulfillmentKey = order.order.fulfillment_status || "unfulfilled";
      fulfillment[fulfillmentKey] = (fulfillment[fulfillmentKey] || 0) + 1;
    }

    // Restore seed
    this.fakerInstance.seed(savedSeed);

    return { states, financial, fulfillment };
  }

  /**
   * Generates a shipping address
   */
  private generateAddress(firstName: string, lastName: string): ShopifyAddress {
    const baseAddress = getWeightedRandomAddress(this.random);
    const phone = this.fakerInstance.phone.number("###-###-####");

    return {
      first_name: firstName,
      last_name: lastName,
      address1: baseAddress.address1,
      address2: baseAddress.address2,
      city: baseAddress.city,
      province: US_STATE_NAMES[baseAddress.state],
      province_code: baseAddress.state,
      zip: baseAddress.zip,
      country: "United States",
      country_code: "US",
      phone,
    };
  }

  /**
   * Generates line items for an order
   */
  private generateLineItems(count: number): ShopifyLineItem[] {
    const items: ShopifyLineItem[] = [];
    const usedProducts = new Set<number>();

    for (let i = 0; i < count; i++) {
      // Select random product (avoid duplicates)
      let productIndex: number;
      do {
        productIndex = this.fakerInstance.number.int({ min: 0, max: PRODUCTS.length - 1 });
      } while (usedProducts.has(productIndex) && usedProducts.size < PRODUCTS.length);
      usedProducts.add(productIndex);

      const product = PRODUCTS[productIndex];
      const quantity = this.fakerInstance.number.int({ min: 1, max: 3 });

      // Add some weight variation (+/- 10%)
      const weightVariation = 1 + (this.random() - 0.5) * 0.2;
      const grams = Math.round(product.gramsBase * weightVariation);

      items.push({
        title: product.title,
        price: product.price,
        quantity,
        grams,
        requires_shipping: true,
        sku: `SKU-${String(productIndex).padStart(4, "0")}`,
      });
    }

    return items;
  }

  /**
   * Generates a random date within past N days
   */
  private generatePastDate(days: number): string {
    const now = new Date();
    const past = new Date(now.getTime() - this.random() * days * 24 * 60 * 60 * 1000);
    return past.toISOString();
  }

  /**
   * Selects an item based on weighted distribution
   */
  private selectWeighted<T>(distribution: { status: T; weight: number }[]): T {
    const roll = this.random();
    let cumulative = 0;

    for (const { status, weight } of distribution) {
      cumulative += weight;
      if (roll < cumulative) {
        return status;
      }
    }

    // Fallback to last item
    return distribution[distribution.length - 1].status;
  }
}

/**
 * Formats order for preview display
 *
 * @param order - Order payload
 * @param index - Order index
 * @returns Formatted string
 */
export function formatOrderPreview(order: ShopifyOrderPayload, index: number): string {
  const addr = order.order.shipping_address;
  const itemCount = order.order.line_items.length;
  const totalGrams = order.order.line_items.reduce((sum, item) => sum + item.grams * item.quantity, 0);
  const totalWeight = (totalGrams / 453.592).toFixed(2); // Convert to lbs

  return [
    `Order #${index + 1}:`,
    `  Email: ${order.order.email}`,
    `  Ship to: ${addr.first_name} ${addr.last_name}`,
    `  Address: ${addr.address1}, ${addr.city}, ${addr.province_code} ${addr.zip}`,
    `  Items: ${itemCount} (${totalWeight} lbs)`,
    `  Financial: ${order.order.financial_status}`,
    `  Fulfillment: ${order.order.fulfillment_status || "unfulfilled"}`,
  ].join("\n");
}
