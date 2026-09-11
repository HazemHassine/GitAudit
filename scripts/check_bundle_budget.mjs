#!/usr/bin/env node

/**
 * GitAudit Deterministic Client JS Bundle Budget Check
 * Compatible with Next.js 16 (App Router with Turbopack or Webpack)
 *
 * Checks compressed (gzip) size of client-side JavaScript assets against deterministic budgets.
 * No optional third-party analyzer dependencies required.
 */

import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const webDir = path.resolve(repoRoot, "apps/web");
const nextDir = path.resolve(webDir, ".next");
const staticDir = path.resolve(nextDir, "static");
const manifestPath = path.resolve(nextDir, "build-manifest.json");

// Budget thresholds (in Kilobytes, 1 KB = 1024 bytes)
// Configurable via environment variables with deterministic defaults
const MAX_SINGLE_CHUNK_GZIP_KB = Number(process.env.BUDGET_MAX_CHUNK_KB) || 150;
const MAX_INITIAL_ROOT_GZIP_KB = Number(process.env.BUDGET_MAX_INITIAL_KB) || 250;
const MAX_TOTAL_CLIENT_JS_GZIP_KB = Number(process.env.BUDGET_MAX_TOTAL_KB) || 400;

function formatKb(bytes) {
  return `${(bytes / 1024).toFixed(2).padStart(8)} KB`;
}

function collectJsFiles(dir) {
  const files = [];
  if (!fs.existsSync(dir)) return files;

  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectJsFiles(fullPath));
    } else if (entry.isFile() && entry.name.endsWith(".js")) {
      files.push(fullPath);
    }
  }
  return files;
}

function main() {
  console.log("================================================================================");
  console.log("        GitAudit Client JS Compressed Bundle Budget Check (Next.js 16)         ");
  console.log("================================================================================");

  if (!fs.existsSync(nextDir)) {
    console.error(`\n[ERROR] Next.js build directory not found: ${nextDir}`);
    console.error("Please run 'npm run build' or 'make build' before checking the bundle budget.\n");
    process.exit(1);
  }

  if (!fs.existsSync(manifestPath)) {
    console.error(`\n[ERROR] Next.js build manifest not found: ${manifestPath}`);
    console.error("Ensure 'next build' completed successfully.\n");
    process.exit(1);
  }

  let buildManifest;
  try {
    const raw = fs.readFileSync(manifestPath, "utf-8");
    buildManifest = JSON.parse(raw);
  } catch (err) {
    console.error(`\n[ERROR] Failed to parse build manifest at ${manifestPath}:`, err);
    process.exit(1);
  }

  // Find all client JavaScript chunks under .next/static/
  const jsFiles = collectJsFiles(staticDir);
  if (jsFiles.length === 0) {
    console.error("\n[ERROR] No client JavaScript chunks discovered under .next/static/\n");
    process.exit(1);
  }

  // Measure size and gzip for each file
  const chunkStats = [];
  const chunkStatsByRelativePath = new Map();

  for (const filePath of jsFiles) {
    const relativeToNext = path.relative(nextDir, filePath).replace(/\\/g, "/");
    const content = fs.readFileSync(filePath);
    const rawSize = content.length;
    const gzipContent = zlib.gzipSync(content, { level: 9 });
    const gzipSize = gzipContent.length;

    const stat = {
      path: relativeToNext,
      rawSize,
      gzipSize,
      gzipKb: gzipSize / 1024,
    };
    chunkStats.push(stat);
    chunkStatsByRelativePath.set(relativeToNext, stat);
  }

  // Sort chunks by gzip size descending
  chunkStats.sort((a, b) => b.gzipSize - a.gzipSize);

  // Compute Root Initial Bundle (rootMainFiles + polyfillFiles)
  const rootFiles = new Set([
    ...(buildManifest.rootMainFiles || []),
    ...(buildManifest.polyfillFiles || []),
  ]);

  let rootRawTotal = 0;
  let rootGzipTotal = 0;
  const missingRootFiles = [];

  for (const rootFile of rootFiles) {
    const stat = chunkStatsByRelativePath.get(rootFile);
    if (stat) {
      rootRawTotal += stat.rawSize;
      rootGzipTotal += stat.gzipSize;
    } else {
      // Check if file exists relative to .next
      const fullPath = path.resolve(nextDir, rootFile);
      if (fs.existsSync(fullPath)) {
        const content = fs.readFileSync(fullPath);
        const gzipped = zlib.gzipSync(content, { level: 9 });
        rootRawTotal += content.length;
        rootGzipTotal += gzipped.length;
      } else {
        missingRootFiles.push(rootFile);
      }
    }
  }

  // Total Client JS
  let totalRawBytes = 0;
  let totalGzipBytes = 0;
  for (const stat of chunkStats) {
    totalRawBytes += stat.rawSize;
    totalGzipBytes += stat.gzipSize;
  }

  // Print Chunk Size Table
  console.log("\nClient JavaScript Chunks (sorted by gzip size):");
  console.log("--------------------------------------------------------------------------------");
  console.log("Chunk Path                                          Raw Size    Gzip Size  Limit");
  console.log("--------------------------------------------------------------------------------");

  let singleChunkBudgetExceeded = false;
  const maxSingleChunkBytes = MAX_SINGLE_CHUNK_GZIP_KB * 1024;

  for (const stat of chunkStats) {
    const chunkExceeded = stat.gzipSize > maxSingleChunkBytes;
    if (chunkExceeded) {
      singleChunkBudgetExceeded = true;
    }
    const flag = chunkExceeded ? "FAIL" : "PASS";
    const shortPath = stat.path.length > 46 ? "..." + stat.path.slice(-43) : stat.path.padEnd(46);
    console.log(`${shortPath}  ${formatKb(stat.rawSize)}  ${formatKb(stat.gzipSize)}  ${flag}`);
  }
  console.log("--------------------------------------------------------------------------------");

  // Summary Metrics
  const largestChunk = chunkStats[0] || { path: "none", gzipSize: 0, rawSize: 0 };
  const largestChunkKb = largestChunk.gzipSize / 1024;
  const rootGzipKb = rootGzipTotal / 1024;
  const totalGzipKb = totalGzipBytes / 1024;

  const largestPass = largestChunkKb <= MAX_SINGLE_CHUNK_GZIP_KB;
  const rootPass = rootGzipKb <= MAX_INITIAL_ROOT_GZIP_KB;
  const totalPass = totalGzipKb <= MAX_TOTAL_CLIENT_JS_GZIP_KB;

  console.log("\nBudget Verification Summary:");
  console.log("--------------------------------------------------------------------------------");
  console.log(`1. Largest Chunk (gzip):      ${formatKb(largestChunk.gzipSize)} / ${formatKb(maxSingleChunkBytes)} [${largestPass ? "PASS" : "FAIL"}]`);
  console.log(`   Chunk: ${largestChunk.path}`);
  console.log(`2. Root Initial Bundle (gzip): ${formatKb(rootGzipTotal)} / ${formatKb(MAX_INITIAL_ROOT_GZIP_KB * 1024)} [${rootPass ? "PASS" : "FAIL"}]`);
  console.log(`   Includes ${rootFiles.size} root entry chunks from build-manifest.json`);
  console.log(`3. Total Client JS (gzip):     ${formatKb(totalGzipBytes)} / ${formatKb(MAX_TOTAL_CLIENT_JS_GZIP_KB * 1024)} [${totalPass ? "PASS" : "FAIL"}]`);
  console.log(`   Across all ${chunkStats.length} client JavaScript chunks`);
  console.log("================================================================================");

  if (missingRootFiles.length > 0 || rootFiles.size === 0) {
    console.error(`[WARN] Some root chunks from manifest were not located on disk: ${missingRootFiles.join(", ")}`);
    process.exit(1);
  }

  const allPassed = largestPass && rootPass && totalPass;

  if (allPassed) {
    console.log("✓ SUCCESS: All client JavaScript compressed bundle budgets PASSED.\n");
    process.exit(0);
  } else {
    console.error("✗ VIOLATION: One or more client JavaScript bundle budgets EXCEEDED.\n");
    if (!largestPass) {
      console.error(`  - Largest chunk (${largestChunk.path}) is ${largestChunkKb.toFixed(2)} KB (budget: ${MAX_SINGLE_CHUNK_GZIP_KB} KB)`);
    }
    if (!rootPass) {
      console.error(`  - Root initial bundle is ${rootGzipKb.toFixed(2)} KB (budget: ${MAX_INITIAL_ROOT_GZIP_KB} KB)`);
    }
    if (!totalPass) {
      console.error(`  - Total client JS is ${totalGzipKb.toFixed(2)} KB (budget: ${MAX_TOTAL_CLIENT_JS_GZIP_KB} KB)`);
    }
    console.error("");
    process.exit(1);
  }
}

main();
