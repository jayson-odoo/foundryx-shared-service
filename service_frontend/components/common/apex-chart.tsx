'use client';

import dynamic from 'next/dynamic';

/**
 * Client-only ApexCharts wrapper. `apexcharts` touches `window` at module load,
 * which crashes SSR (`next start`). Importing it via next/dynamic with ssr:false
 * keeps it out of the server bundle. Use this instead of `react-apexcharts`.
 */
const ApexChart = dynamic(() => import('react-apexcharts'), { ssr: false });

export default ApexChart;
