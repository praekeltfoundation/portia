FROM praekeltfoundation/python-base:latest

RUN pip install portia

CMD ["portia", "run", "--web-endpoint", "tcp:8000"]
