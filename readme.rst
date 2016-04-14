Simple Storage Service Static Site Uploader
===========================================

A tool for uploading static websites to Amazon S3. s5upload

* uploads only files which were changed,
* sets :code:`Cache-Control` for you,
* invalidates CloudFront cache for you,
* is not dependent on any particular static site generator like Jekyll.

In comparison to :code:`s3_website` this tool is written in
Python 3 and does not do things which can be easily done in AWS Console.


Install
-------

* Install dependencies :code:`pip install awscli boto3 pyyaml`
* In AWS create an IAM user with permissions to manipulate your S3 and
  CloudFront settings. Then run :code:`aws configure` in your terminal.
* Download :code:`s5upload.py` (with curl :code:`curl -O https://raw.githubusercontent.com/OndrejSlamecka/s5upload/master/s5upload.py`)
* Allow executing :code:`chmod +x s5upload.py`

(If you would like to install this with :code:`pip` then just give this
project a star -- when it gets few stars I will make a pypi package)


Run
---

::

    # Start by opening the help
    ./s5upload.py -h

    # Upload the contents of _site to bucket called example.com
    ./s5upload.py -d _site -b example.com

    # Upload the contents of _site to bucket called example.com
    # and purge the cache of CloudFront distribution with ID XXXX
    ./s5upload.py -d _site -b example.com -cf XXXX

    # Create a configuration file to avoid re-typing common arguments
    ./s5upload.py -p -d _site -b example.com -cf XXXX > s5upload.yml

    # Run again
    ./s5upload.py


The default configuration of cache-control should be good enough for
most use cases. If you want to modify it just know that it uses Python's
regular expressions.


Contributing
------------

If you want to change the code just create a pull request. Please check
your source code with the :code:`flake8` tool. If you want to contribute but
do not know what to do I suggest you to create unit tests :-)

If this tool saved you some time and you want to support its development
with a donation please `use Paypal
<https://www.slamecka.cz/misc/s5upload/>`_.


License
-------

GNU General Public License, see the :code:`LICENSE` file.

Author: Ondrej Slamecka <ondrej@slamecka.cz>
