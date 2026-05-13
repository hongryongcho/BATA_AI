module.exports = {
  apps: [
    {
      name: 'bata-stock-backend',
      script: 'src/index.js',
      cwd: '/Users/batagota/BATAGOTA/10_AI_BATA/01_BATA_STOCK/backend',
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        NODE_ENV: 'production',
      },
    },
  ],
};
