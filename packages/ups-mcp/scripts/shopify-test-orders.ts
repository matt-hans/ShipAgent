#!/usr/bin/env npx tsx
/**
 * Shopify Test Order Generator CLI
 *
 * Generate 1000+ test orders in Shopify for benchmarking ShipAgent.
 *
 * Commands:
 *   generate  Generate test orders
 *   cleanup   Remove all test orders
 *   status    Check generation progress
 *   verify    Verify order distribution
 *
 * Usage:
 *   npm run shopify:generate -- --count 1000
 *   npm run shopify:generate -- --count 1000 --resume
 *   npm run shopify:cleanup
 *   npm run shopify:status
 *   npm run shopify:verify
 */

import { Command } from "commander";
import ora from "ora";
import pLimit from "p-limit";
import { ShopifyClient, createShopifyClientFromEnv, ShopifyApiError } from "./lib/shopify-client.js";
import { OrderGenerator, TEST_ORDER_TAG, formatOrderPreview } from "./lib/order-generator.js";
import { ProgressTracker, getDefaultTracker } from "./lib/progress-tracker.js";
import type { GenerateOptions, CleanupOptions, VerifyOptions, GenerationStats } from "./lib/types.js";

const program = new Command();

program
  .name("shopify-test-orders")
  .description("Generate test orders in Shopify for ShipAgent benchmarking")
  .version("1.0.0");

// =============================================================================
// Generate Command
// =============================================================================

program
  .command("generate")
  .description("Generate test orders in Shopify")
  .option("-c, --count <number>", "Number of orders to generate", "1000")
  .option("-r, --resume", "Resume from previous interrupted run", false)
  .option("-d, --dry-run", "Preview without creating orders", false)
  .option("--concurrency <number>", "Concurrent requests (1-10)", "2")
  .option("--seed <number>", "Random seed for reproducibility")
  .action(async (opts) => {
    const options: GenerateOptions = {
      count: parseInt(opts.count, 10),
      resume: opts.resume,
      dryRun: opts.dryRun,
      concurrency: Math.min(10, Math.max(1, parseInt(opts.concurrency, 10))),
      seed: opts.seed ? parseInt(opts.seed, 10) : undefined,
    };

    await generateOrders(options);
  });

// =============================================================================
// Cleanup Command
// =============================================================================

program
  .command("cleanup")
  .description("Remove all test orders from Shopify")
  .option("-a, --all", "Delete all orders with shipagent-test tag (not just tracked)", false)
  .option("-f, --force", "Skip confirmation prompt", false)
  .action(async (opts) => {
    const options: CleanupOptions = {
      all: opts.all,
      force: opts.force,
    };

    await cleanupOrders(options);
  });

// =============================================================================
// Status Command
// =============================================================================

program
  .command("status")
  .description("Check generation progress")
  .action(async () => {
    const tracker = getDefaultTracker();
    const state = tracker.load();

    if (!state) {
      console.log("No active or previous generation session found.");
      return;
    }

    console.log("\n" + tracker.formatStatus() + "\n");
  });

// =============================================================================
// Verify Command
// =============================================================================

program
  .command("verify")
  .description("Verify created orders and their distribution")
  .option("-d, --detailed", "Show detailed distribution analysis", false)
  .action(async (opts) => {
    const options: VerifyOptions = {
      detailed: opts.detailed,
    };

    await verifyOrders(options);
  });

// =============================================================================
// Generate Implementation
// =============================================================================

async function generateOrders(options: GenerateOptions): Promise<void> {
  const spinner = ora();
  const tracker = getDefaultTracker();

  // Validate options
  if (options.count < 1 || options.count > 10000) {
    console.error("Error: Count must be between 1 and 10000");
    process.exit(1);
  }

  // Dry run mode - skip state management
  if (options.dryRun) {
    const seed = options.seed || Math.floor(Math.random() * 1000000);
    const generator = new OrderGenerator({ seed, startIndex: 0 });

    console.log("\n=== DRY RUN MODE ===\n");
    console.log(`Would generate ${options.count} orders with seed ${seed}\n`);

    // Show distribution preview
    const stats = generator.getDistributionStats(Math.min(options.count, 100));
    console.log("State distribution preview:");
    Object.entries(stats.states)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
      .forEach(([state, count]) => {
        const pct = ((count / Math.min(options.count, 100)) * 100).toFixed(1);
        console.log(`  ${state}: ${count} (${pct}%)`);
      });

    console.log("\nFinancial status distribution:");
    Object.entries(stats.financial).forEach(([status, count]) => {
      const pct = ((count / Math.min(options.count, 100)) * 100).toFixed(1);
      console.log(`  ${status}: ${count} (${pct}%)`);
    });

    console.log("\nFulfillment status distribution:");
    Object.entries(stats.fulfillment).forEach(([status, count]) => {
      const pct = ((count / Math.min(options.count, 100)) * 100).toFixed(1);
      console.log(`  ${status}: ${count} (${pct}%)`);
    });

    console.log("\nSample orders:");
    for (let i = 0; i < Math.min(3, options.count); i++) {
      console.log("\n" + formatOrderPreview(generator.generateOrder(i), i));
    }

    return;
  }

  // Check for resume
  let state = tracker.load();
  let startIndex = 0;
  let seed: number;

  if (options.resume && state && !state.completed) {
    startIndex = state.nextIndex;
    seed = state.seed;
    console.log(`\nResuming from order ${startIndex + 1} of ${state.targetCount}`);
    console.log(`Previously created: ${state.createdOrderIds.length} orders`);
    console.log(`Errors: ${state.errors.length}\n`);
  } else if (options.resume && state?.completed) {
    console.log("Previous session completed. Starting fresh.");
    tracker.delete();
    state = null;
    seed = options.seed || Math.floor(Math.random() * 1000000);
    tracker.initialize({ targetCount: options.count, seed });
  } else {
    // Fresh start
    if (state && !state.completed) {
      console.log("Warning: Previous incomplete session found. Use --resume to continue or delete state file.");
      const readline = await import("readline");
      const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
      const answer = await new Promise<string>((resolve) => {
        rl.question("Start fresh and lose progress? (y/N): ", resolve);
      });
      rl.close();

      if (answer.toLowerCase() !== "y") {
        console.log("Aborted. Use --resume to continue previous session.");
        return;
      }
      tracker.delete();
    }

    seed = options.seed || Math.floor(Math.random() * 1000000);
    tracker.initialize({ targetCount: options.count, seed });
  }

  // Initialize generator
  const generator = new OrderGenerator({ seed, startIndex });

  // Create Shopify client
  let client: ShopifyClient;
  try {
    client = createShopifyClientFromEnv();
  } catch (error) {
    console.error("\nError:", (error as Error).message);
    console.error("\nRequired environment variables:");
    console.error("  SHOPIFY_STORE_DOMAIN - Your Shopify store domain (e.g., my-store.myshopify.com)");
    console.error("  SHOPIFY_ACCESS_TOKEN - Admin API access token");
    console.error("\nOptional:");
    console.error("  SHOPIFY_API_VERSION  - API version (default: 2024-01)");
    console.error("  SHOPIFY_RATE_LIMIT   - Requests per second (default: 2)");
    process.exit(1);
  }

  // Generate orders
  const startTime = Date.now();
  const limit = pLimit(options.concurrency);
  let successCount = 0;
  let errorCount = 0;

  console.log(`\nGenerating ${options.count - startIndex} orders...`);
  spinner.start(`Creating orders (0/${options.count - startIndex})`);

  // Create all order promises
  const tasks: Promise<void>[] = [];

  for (let i = startIndex; i < options.count; i++) {
    const task = limit(async () => {
      const order = generator.generateOrder(i - startIndex);

      try {
        const response = await client.createOrder(order);
        tracker.recordSuccess(i, response.order.id);
        successCount++;
        spinner.text = `Creating orders (${successCount + errorCount}/${options.count - startIndex}) - ${successCount} success, ${errorCount} errors`;
      } catch (error) {
        const message = error instanceof ShopifyApiError
          ? `API Error ${error.status}: ${typeof error.errors === "string" ? error.errors : JSON.stringify(error.errors)}`
          : (error as Error).message;

        tracker.recordError(i, message);
        errorCount++;
        spinner.text = `Creating orders (${successCount + errorCount}/${options.count - startIndex}) - ${successCount} success, ${errorCount} errors`;
      }
    });

    tasks.push(task);
  }

  // Wait for all to complete
  await Promise.all(tasks);

  // Mark complete and save final state
  tracker.markComplete();
  tracker.save();

  const elapsed = Date.now() - startTime;
  spinner.succeed(`Completed in ${(elapsed / 1000).toFixed(1)}s`);

  // Print summary
  console.log("\n=== Generation Summary ===");
  console.log(`Total: ${options.count - startIndex}`);
  console.log(`Success: ${successCount}`);
  console.log(`Errors: ${errorCount}`);
  console.log(`Rate: ${((successCount / elapsed) * 1000).toFixed(2)} orders/sec`);
  console.log(`Seed: ${seed}`);

  if (errorCount > 0) {
    console.log("\nRecent errors:");
    const recentErrors = tracker.getState()?.errors.slice(-5) || [];
    recentErrors.forEach((err) => {
      console.log(`  [${err.index}] ${err.message}`);
    });
  }
}

// =============================================================================
// Cleanup Implementation
// =============================================================================

async function cleanupOrders(options: CleanupOptions): Promise<void> {
  const spinner = ora();
  const tracker = getDefaultTracker();

  // Get client
  let client: ShopifyClient;
  try {
    client = createShopifyClientFromEnv();
  } catch (error) {
    console.error("\nError:", (error as Error).message);
    process.exit(1);
  }

  // Get order IDs to delete
  let orderIds: number[] = [];

  if (options.all) {
    // Fetch all orders with test tag
    spinner.start("Fetching test orders from Shopify...");

    try {
      let hasMore = true;
      let sinceId: number | undefined;

      while (hasMore) {
        const response = await client.listOrders({
          status: "any",
          tags: TEST_ORDER_TAG,
          limit: 250,
          since_id: sinceId,
          fields: "id",
        });

        if (response.orders.length === 0) {
          hasMore = false;
        } else {
          orderIds.push(...response.orders.map((o) => o.id));
          sinceId = response.orders[response.orders.length - 1].id;
          spinner.text = `Fetching test orders from Shopify... (${orderIds.length} found)`;
        }
      }

      spinner.succeed(`Found ${orderIds.length} test orders`);
    } catch (error) {
      spinner.fail("Failed to fetch orders");
      console.error((error as Error).message);
      process.exit(1);
    }
  } else {
    // Use tracked order IDs
    const state = tracker.load();
    if (!state) {
      console.log("No tracked orders found. Use --all to search for test orders in Shopify.");
      return;
    }
    orderIds = state.createdOrderIds;
    console.log(`Found ${orderIds.length} tracked orders`);
  }

  if (orderIds.length === 0) {
    console.log("No orders to delete.");
    return;
  }

  // Confirmation
  if (!options.force) {
    const readline = await import("readline");
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    const answer = await new Promise<string>((resolve) => {
      rl.question(`Delete ${orderIds.length} orders? (y/N): `, resolve);
    });
    rl.close();

    if (answer.toLowerCase() !== "y") {
      console.log("Aborted.");
      return;
    }
  }

  // Delete orders
  const startTime = Date.now();
  const limit = pLimit(2); // Conservative rate limit for deletes
  let successCount = 0;
  let errorCount = 0;

  spinner.start(`Deleting orders (0/${orderIds.length})`);

  const tasks = orderIds.map((orderId) =>
    limit(async () => {
      try {
        await client.deleteOrder(orderId);
        successCount++;
      } catch (error) {
        // Order might already be deleted
        if (error instanceof ShopifyApiError && error.status === 404) {
          successCount++; // Count as success
        } else {
          errorCount++;
        }
      }
      spinner.text = `Deleting orders (${successCount + errorCount}/${orderIds.length})`;
    })
  );

  await Promise.all(tasks);

  const elapsed = Date.now() - startTime;
  spinner.succeed(`Deleted ${successCount} orders in ${(elapsed / 1000).toFixed(1)}s`);

  if (errorCount > 0) {
    console.log(`Failed to delete: ${errorCount} orders`);
  }

  // Clean up state file
  tracker.delete();
  console.log("State file cleaned up.");
}

// =============================================================================
// Verify Implementation
// =============================================================================

async function verifyOrders(options: VerifyOptions): Promise<void> {
  const spinner = ora();

  // Get client
  let client: ShopifyClient;
  try {
    client = createShopifyClientFromEnv();
  } catch (error) {
    console.error("\nError:", (error as Error).message);
    process.exit(1);
  }

  spinner.start("Counting test orders...");

  try {
    // Count all test orders
    const totalCount = await client.countOrders({
      status: "any",
      tags: TEST_ORDER_TAG,
    });

    spinner.succeed(`Found ${totalCount} test orders`);

    if (totalCount === 0) {
      return;
    }

    if (options.detailed) {
      spinner.start("Analyzing order distribution...");

      // Fetch all orders for analysis
      const orders: Array<{
        id: number;
        financial_status: string;
        fulfillment_status: string | null;
      }> = [];

      let hasMore = true;
      let sinceId: number | undefined;

      while (hasMore) {
        const response = await client.listOrders({
          status: "any",
          tags: TEST_ORDER_TAG,
          limit: 250,
          since_id: sinceId,
          fields: "id,financial_status,fulfillment_status",
        });

        if (response.orders.length === 0) {
          hasMore = false;
        } else {
          orders.push(...response.orders);
          sinceId = response.orders[response.orders.length - 1].id;
          spinner.text = `Analyzing orders... (${orders.length}/${totalCount})`;
        }
      }

      spinner.succeed("Analysis complete");

      // Calculate distributions
      const financial: Record<string, number> = {};
      const fulfillment: Record<string, number> = {};

      orders.forEach((order) => {
        financial[order.financial_status] = (financial[order.financial_status] || 0) + 1;
        const fulfillmentKey = order.fulfillment_status || "unfulfilled";
        fulfillment[fulfillmentKey] = (fulfillment[fulfillmentKey] || 0) + 1;
      });

      console.log("\n=== Order Distribution ===\n");

      console.log("Financial Status:");
      Object.entries(financial)
        .sort((a, b) => b[1] - a[1])
        .forEach(([status, count]) => {
          const pct = ((count / orders.length) * 100).toFixed(1);
          console.log(`  ${status}: ${count} (${pct}%)`);
        });

      console.log("\nFulfillment Status:");
      Object.entries(fulfillment)
        .sort((a, b) => b[1] - a[1])
        .forEach(([status, count]) => {
          const pct = ((count / orders.length) * 100).toFixed(1);
          console.log(`  ${status}: ${count} (${pct}%)`);
        });
    }

    // Show quick stats
    console.log("\n=== Quick Test Queries ===");
    console.log("To test ShipAgent with these orders:");
    console.log('  "Show unfulfilled orders from California"');
    console.log('  "Ship first 5 orders via UPS Ground"');
    console.log('  "List all paid orders from New York"');
  } catch (error) {
    spinner.fail("Failed to verify orders");
    console.error((error as Error).message);
    process.exit(1);
  }
}

// =============================================================================
// Run CLI
// =============================================================================

program.parse();
