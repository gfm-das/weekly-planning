// The ```chart code block (manager/gfm-addon/setup/transformers.ts), loaded
// with Node's own TypeScript type stripping. Plain Node, no packages.
import test from 'node:test';
import assert from 'node:assert/strict';
import transformers from '../manager/gfm-addon/setup/transformers.ts';

const [block] = transformers().codeblocks;
const propsOf = (info, code = 'Week,A\n1,2') => {
  const html = block({ info, code });
  const json = html.match(/v-bind='(.*)' \/>$/)[1];
  return JSON.parse(json);
};

test('old keys work as before', () => {
  assert.deepEqual(propsOf('chart type=bar trend=polynomial degree=3 title="Members at lessons" show-values colors=#00869e,#d96b2b max=10 height=300'), {
    csv: 'Week,A\n1,2', type: 'bar', trend: 'polynomial', degree: 3, title: 'Members at lessons', showValues: true, colors: ['#00869e', '#d96b2b'], max: 10, height: 300,
  });
  assert.equal(block({ info: 'js', code: 'x' }), undefined);
});

test('new keys: text, numbers, switches, lists and the override', () => {
  const props = propsOf(`chart type=line trend=moving-average window=4 forecast=3 trend-color=#ff0000 trend-style=dotted trend-width=3 trend-label="Four weeks" target=30 target-label=Goal average stack=false horizontal smooth=true legend=bottom x-title=Week y-title="People" y-min=0 y-max=50 label-rotate=45 format=percent decimals=1 prefix=€ suffix=" ppl" value-position=inside data-zoom multiples series-types=bar,line goal=Goal goal-color=#00ff00 option='{"yAxis":{"min":0}}'`);
  assert.deepEqual(props, {
    csv: 'Week,A\n1,2', type: 'line', trend: 'moving-average', window: 4, forecast: 3, trendColor: '#ff0000', trendStyle: 'dotted', trendWidth: 3, trendLabel: 'Four weeks',
    target: 30, targetLabel: 'Goal', average: true, stack: false, horizontal: true, smooth: true, legend: 'bottom', xTitle: 'Week', yTitle: 'People',
    yMin: 0, yMax: 50, labelRotate: 45, format: 'percent', decimals: 1, prefix: '€', suffix: ' ppl', valuePosition: 'inside', dataZoom: true, multiples: true,
    seriesTypes: ['bar', 'line'], goal: 'Goal', goalColor: '#00ff00', option: '{"yAxis":{"min":0}}',
  });
  assert.deepEqual(propsOf('chart trendColor=#123456 target=abc'), { csv: 'Week,A\n1,2', trendColor: '#123456' }, 'camelCase works; a bad number is left out');
});

test('quotes and tags cannot break the slide', () => {
  const html = block({ info: `chart title="<b>'x'</b> & y" option='{"a":"</script>"}'`, code: 'A,B\n1,2' });
  assert.ok(!/<b>|<\/script>|'x'/.test(html.replace(/^<MissionChart v-bind='|' \/>$/g, '')));
});
