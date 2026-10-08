// Rasterize the existing SVG mark after generate_site.py; no redesign or external assets.
// Run: node scripts/generate_favicons.js (uses the same browser as the local tests).
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('@playwright/test');
const web = path.resolve(__dirname, '../web');
const chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

async function main() {
  const browser = await chromium.launch(fs.existsSync(chrome) ? {executablePath: chrome} : {});
  try {
    const page = await browser.newPage();
    const svg = fs.readFileSync(path.join(web, 'favicon.svg'), 'utf8');
    const frames = [];
    const outputs = {96: 'favicon.png', 180: 'apple-touch-icon.png',
      192: 'android-chrome-192x192.png', 512: 'android-chrome-512x512.png'};
    for (const size of [16, 32, 48, 96, 180, 192, 512]) {
      const data = await page.evaluate(async ({svg, size}) => {
        const image = new Image();
        // Explicit dimensions let browsers rasterize a viewBox-only SVG into a canvas.
        image.src = 'data:image/svg+xml,' + encodeURIComponent(svg.replace('<svg ', '<svg width="64" height="64" '));
        await image.decode();
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = size;
        const context = canvas.getContext('2d');
        // Home-screen icons need an opaque background; the OS applies its own mask.
        if (size >= 180) {
          context.fillStyle = '#0b1426';
          context.fillRect(0, 0, size, size);
        }
        context.drawImage(image, 0, 0, size, size);
        return canvas.toDataURL('image/png').split(',')[1];
      }, {svg, size});
      const png = Buffer.from(data, 'base64');
      if (outputs[size]) fs.writeFileSync(path.join(web, outputs[size]), png);
      else frames.push({size, png});
    }
    // ICO directory followed by PNG-compressed frames, supported by modern browsers.
    const directory = Buffer.alloc(6 + 16 * frames.length);
    directory.writeUInt16LE(1, 2);
    directory.writeUInt16LE(frames.length, 4);
    let offset = directory.length;
    frames.forEach(({size, png}, i) => {
      const entry = 6 + i * 16;
      directory[entry] = directory[entry + 1] = size;
      directory.writeUInt16LE(1, entry + 4);
      directory.writeUInt16LE(32, entry + 6);
      directory.writeUInt32LE(png.length, entry + 8);
      directory.writeUInt32LE(offset, entry + 12);
      offset += png.length;
    });
    fs.writeFileSync(path.join(web, 'favicon.ico'), Buffer.concat([directory, ...frames.map(f => f.png)]));
    console.log('Generated favicon PNG/ICO, Apple touch icon (180×180), and Android icons (192×192/512×512) from favicon.svg.');
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
