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
    for (const size of [16, 32, 48, 96]) {
      const data = await page.evaluate(async ({svg, size}) => {
        const image = new Image();
        // Explicit dimensions let browsers rasterize a viewBox-only SVG into a canvas.
        image.src = 'data:image/svg+xml,' + encodeURIComponent(svg.replace('<svg ', '<svg width="64" height="64" '));
        await image.decode();
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = size;
        canvas.getContext('2d').drawImage(image, 0, 0, size, size);
        return canvas.toDataURL('image/png').split(',')[1];
      }, {svg, size});
      const png = Buffer.from(data, 'base64');
      if (size === 96) fs.writeFileSync(path.join(web, 'favicon.png'), png);
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
    console.log('Generated favicon.png (96×96) and favicon.ico (16/32/48) from favicon.svg.');
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
