from setuptools import setup, find_packages

setup(
    name='my-bot',
    version='0.1.0',
    packages=find_packages(),
    install_requires=[
        'telethon==1.34.0',
    ],
)
