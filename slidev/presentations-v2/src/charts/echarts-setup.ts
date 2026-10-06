// Apache ECharts 6 from its modular entry (echarts/core): only the chart types and parts the presets use.
// TODO: lazy-load the rarer chart types (radar, heatmap, sankey ...) when the Advanced JSON asks for them.
import * as echarts from 'echarts/core';
import { BarChart, FunnelChart, GaugeChart, LineChart, PieChart, ScatterChart } from 'echarts/charts';
import { DatasetComponent, GridComponent, LegendComponent, MarkLineComponent, TitleComponent, TooltipComponent, TransformComponent } from 'echarts/components';
import { LabelLayout, UniversalTransition } from 'echarts/features';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  BarChart, LineChart, PieChart, ScatterChart, GaugeChart, FunnelChart,
  GridComponent, TooltipComponent, LegendComponent, TitleComponent, DatasetComponent, TransformComponent, MarkLineComponent,
  LabelLayout, UniversalTransition, CanvasRenderer,
]);

export { echarts };
