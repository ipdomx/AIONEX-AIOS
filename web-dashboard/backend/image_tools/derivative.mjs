import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import sharp from "sharp";

const ALLOWED_FORMATS = new Set(["png", "jpeg", "webp"]);
const ALLOWED_FITS = new Set(["cover", "contain"]);
const ALLOWED_POSITIONS = new Set(["centre", "center", "north", "south", "east", "west"]);
const MAX_DIMENSION = 8192;

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(2);
}

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) fail("invalid derivative arguments");
    values[key.slice(2)] = value;
  }
  const width = Number.parseInt(values.width ?? "", 10);
  const height = Number.parseInt(values.height ?? "", 10);
  const format = values.format ?? "";
  const fit = values.fit ?? "cover";
  const position = values.position ?? "centre";
  if (!values.input || !values.output) fail("input/output path is required");
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || width > MAX_DIMENSION || height > MAX_DIMENSION) {
    fail("derivative dimensions are outside the governed range");
  }
  if (!ALLOWED_FORMATS.has(format)) fail("derivative format is unsupported");
  if (!ALLOWED_FITS.has(fit)) fail("derivative fit is unsupported");
  if (!ALLOWED_POSITIONS.has(position)) fail("derivative position is unsupported");
  return { input: values.input, output: values.output, width, height, format, fit, position };
}

async function run() {
  const rawArgs = process.argv.slice(2);
  if (rawArgs.length === 1 && rawArgs[0] === "--probe") {
    const sharpVersion = sharp.versions?.sharp ?? "unknown";
    const libvipsVersion = sharp.versions?.vips ?? "unknown";
    if (sharpVersion !== "0.35.3") fail("unexpected Sharp runtime version");
    process.stdout.write(JSON.stringify({ engine: "sharp", engine_version: sharpVersion, libvips_version: libvipsVersion }));
    return;
  }
  const spec = parseArgs(rawArgs);
  const inputPath = path.resolve(spec.input);
  const outputPath = path.resolve(spec.output);
  if (inputPath === outputPath) fail("derivative input and output paths must differ");
  const inputStat = await fs.stat(inputPath);
  if (!inputStat.isFile() || inputStat.size < 1) fail("derivative input is unavailable");

  const input = sharp(inputPath, { failOn: "warning", limitInputPixels: 100_000_000, sequentialRead: true });
  const inputMeta = await input.metadata();
  const inputFormat = inputMeta.format === "jpg" ? "jpeg" : inputMeta.format;
  if (!ALLOWED_FORMATS.has(inputFormat) || !inputMeta.width || !inputMeta.height) fail("derivative input raster is unsupported");
  if (inputMeta.width > 16384 || inputMeta.height > 16384) fail("derivative input dimensions are outside the governed range");
  if (spec.format === "jpeg" && inputMeta.hasAlpha) {
    const stats = await sharp(inputPath, { failOn: "warning", limitInputPixels: 100_000_000, sequentialRead: true }).stats();
    const alpha = stats.channels.at(-1);
    if (alpha && alpha.min < 255) fail("transparent source cannot be exported as JPEG");
  }

  let pipeline = sharp(inputPath, { failOn: "warning", limitInputPixels: 100_000_000, sequentialRead: true })
    .rotate()
    .resize({ width: spec.width, height: spec.height, fit: spec.fit, position: spec.position, withoutEnlargement: false, fastShrinkOnLoad: true });
  if (spec.format === "png") {
    pipeline = pipeline.png({ compressionLevel: 9, adaptiveFiltering: false, palette: false });
  } else if (spec.format === "jpeg") {
    pipeline = pipeline.jpeg({ quality: 92, chromaSubsampling: "4:4:4", mozjpeg: false, progressive: false });
  } else {
    pipeline = pipeline.webp({ quality: 92, effort: 6, smartSubsample: false, nearLossless: false });
  }
  const info = await pipeline.toFile(outputPath);
  const outputMeta = await sharp(outputPath, { failOn: "warning", limitInputPixels: 100_000_000 }).metadata();
  const outputFormat = outputMeta.format === "jpg" ? "jpeg" : outputMeta.format;
  if (outputFormat !== spec.format || outputMeta.width !== spec.width || outputMeta.height !== spec.height) {
    fail("derivative output verification failed");
  }
  const sharpVersion = sharp.versions?.sharp ?? "unknown";
  if (sharpVersion !== "0.35.3") fail("unexpected Sharp runtime version");
  process.stdout.write(JSON.stringify({
    engine: "sharp",
    engine_version: sharpVersion,
    input_format: inputFormat,
    input_width: inputMeta.width,
    input_height: inputMeta.height,
    input_has_alpha: Boolean(inputMeta.hasAlpha),
    output_format: outputFormat,
    output_width: outputMeta.width,
    output_height: outputMeta.height,
    output_has_alpha: Boolean(outputMeta.hasAlpha),
    output_size: info.size,
    fit: spec.fit,
    position: spec.position
  }));
}

run().catch((error) => fail(error instanceof Error ? error.message : "derivative transform failed"));
