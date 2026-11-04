// node tones.js : print the tone cues for each sample sentence (a quick check without a browser)
global.window = global; global.document = {};
require('../engine.js');
const T = window.CMP_TRACK;
for (const t of process.argv.slice(2).length ? process.argv.slice(2) : require('fs').readFileSync(__dirname + '/../../../../org/tasks/j-expressions/frames/sentences.txt', 'utf8').split('\n').filter(Boolean).map(l => l.split('\t')[1])) {
  let u = 0; const wd = t.split(' ').map((w, i) => [i, u += .33, u + .3, w + ' ', i === 0 ? 1 : 0]);
  console.log(T.buildTrack(wd).map(c => c.tone + '@' + wd[c.i][3].trim()).join(' > ').padEnd(60), '|', t);
}
