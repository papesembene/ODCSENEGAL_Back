 
app.config['ELASTIC_APM'] = {
    'SERVICE_NAME': 'https://apm.seetlu.orange-sonatel.com',
    'SECRET_TOKEN': 'S815842vHGvkR0sr0P5s1Zje',
}
apm = ElasticAPM(app)