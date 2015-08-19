from __future__ import with_statement
#/***********************************************************************
# * Licensed Materials - Property of IBM 
# *
# * IBM SPSS Products: Statistics Common
# *
# * (C) Copyright IBM Corp. 1989, 2013
# *
# * US Government Users Restricted Rights - Use, duplication or disclosure
# * restricted by GSA ADP Schedule Contract with IBM Corp. 
# ************************************************************************/
"""SPSSINC ANON extension command"""

__author__ =  'spss, JKP'
__version__=  '1.0.0'

helptext = """
SPSSINC ANON.  Anonymize a set of variables.

SPSSINC ANON  VARIABLES=varnames
[/OPTIONS [SVALUEROOT='prefix'] [NAMEROOT=nprefix] 
[METHOD={SEQUENTIAL*|TRANSFORM|RANDOM}]
[SEED=number] [OFFSET=number] [SCALE=number]]
[MAXRVALUE=positive integer or list of integers]
[ONETOONE = varnames]
[MAPPING= input filespec]
[/SAVE [NAMEMAPPING=filespec] [VALUEMAPPING=filespec]]
[/HELP]

Example:
SPSSINC ANON x y z
/OPTIONS METHOD=RANDOM
/SAVE VALUEMAPPING="c:/temp/values.txt".

This command replaces the values of the specified variables with new values
according to one of three methods.  It is intended for situations where the
true values must be concealed for privacy or other reasons.  It can also
replace the variables names with anonymous equivalents.

VARIABLES specifies the list of variables to anonymize.

METHOD specifies how to generate the new values.
SEQUENTIAL replaces each value with a sequential number.  If a value
recurs for a variable, it gets the same number.
RANDOM replaces the values with a random integer in the range [0, MAXRVALUES].
TRANSFORM, which applies only to numeric variables, calculates a new value
according to the formula OFFSET + SCALE * value.  If TRANSFORM is
specified and the variable list includes strings, SEQUENTIAL will be used
for those variables.
System-missing values are treated as the same value across cases, and for
TRANSFORM, the new value will also be system missing.

MAXRVALUES, which applies only to the RANDOM method, can be a single integer
applied to all variables or a list of as many integers as there are variables being
anonymized.  For string variables, the range is further limited by the declared
string width.

TRANSFORM and SEQUENTIAL will produce unique values as long as, in the case
of SEQUENTIAL with string variables, the field is wide enough.  For RANDOM,
you can specify a list of one or more variables as ONETOONE, which will
generate unique values if that is possible.  If unique values cannot be generated, the
procedure will stop with an error message.  Using ONETOONE increases the time and
memory requirements.

For repeatability, you can specify a numerical value for SEED that will produce the
same results if the syntax is rerun at a later time with the same inputs.

If the variable is a string, SVALUEROOT can specify a string to be prefixed
to the new integer values if the string is wide enough.

If NAMEROOT is specified, the variables will be renamed to the form
xxxnnn
where xxx is the NAMEROOT value and xxx is an integer.

The SAVE parameters create text files containing the mapping of variable names,
if any, and old and new values.  The new-values file is in csv format.
The new values are listed alphabetically by the new
value within variable for ease of lookup.  As explained above, the inverse mapping 
is sometimes not unique.

A new-values file can be used as input in a later run by specifying it in
MAPPING if the method is SEQUENTIAL or RANDOM.  If given, any variable mappings defined in 
that file are applied to the input values before applying the chosen method.
This means that previously encountered values are mapped the same way
as they were previously.  However, if MAXRVALUE is different or the string
width is different, the results are undefined.

There are side effects to this command.  Value labels and missing value definitions
are cleared, since they no longer apply.  You can anonymize date-format variables, but the
resulting values will usually not display as the values are not in the valid range for dates.
Changing the variable type to numeric will allow the values to display.

/HELP displays this help and does nothing else.
"""
import spss, spssaux
from extension import Template, Syntax, processcmd
import sys, random, re, codecs, csv, cStringIO
from operator import itemgetter

#try:
    #import wingdbstub
#except:
    #pass

trailingdigits = re.compile(r"\d+$")

# determine a reasonable line end sequence for files based on the os
try:
    sys.getwindowsversion()  # only available for Windows
    lineend = "\r\n"
except:
    lineend = "\n"

class DataStep(object):
    def __enter__(self):
        """initialization for with statement"""
        try:
            spss.StartDataStep()
        except:
            spss.Submit("EXECUTE")
            spss.StartDataStep()
        return self
    
    def __exit__(self, type, value, tb):
        spss.EndDataStep()
        return False



def anon(varnames, nameroot=None, svalueroot='', method='sequential',
    seed=None, offset=None, scale=None, maxrvalue = None, onetoone=None, 
    namemapping=None, valuemapping=None, mapping=None, ignorethis=None):
    """Anonymize the specified variables
    
    varnames is the list of input variables.
    nameroot, if specified, is used as a prefix to rename variables with a numerical suffix.
    svalueroot, if specified, gives a prefix to be prepended to transformed values
    of string variables.
    method = 'sequential' (default), 'random', or 'transform'.
    seed, if specified, is used to initialize the random number generator
    offset and scale, required if method=transform, are the parameters for a
    linear transform of the values.  If specified for a string variable , sequential is substituted.
    System-missing values are left as sysmis.
    maxrvalue is the maximum value for the random method.  Must be positive.  Only applies
    to random method.
    Can be one value for all variables or a list the size of the variable list with variable-specific
    values
    onetoone is an option list of variable names, a subset of varnames, for which mapped
      values must be unique.  Applies only to method random.  If 1-1 mapping cannot be
      found, an exception is raised.
    namemapping and valuemapping determine whether files with tables of results are saved.
    mapping names a file written as valuemapping to be used to initialize random mappings.
    """
    
    with DataStep():
        ds = spss.Dataset()
        allvariables = ds.varlist
        varnums = [allvariables[v].index for v in varnames] 
        numvars = len(varnums)       
        if maxrvalue is None: 
            maxrvalue = [9999999]
        if len(maxrvalue) == 1:
            maxrvalue = numvars * maxrvalue
        if len(maxrvalue) != numvars:
            raise ValueError("The number of values for maxrvalue is different from the number of variables")
        if onetoone is None:
            onetoone = []
        onetoone = set([allvariables[v].index for v in onetoone])
        if not onetoone.issubset(set(varnums)):
            raise ValueError("A variable is listed in ONETOONE that is not in the VARIABLES list")
        if seed:
            random.seed(seed)
        

        trflist = [Tvar(allvariables[vn], svalueroot, method, offset, 
            scale, maxrvalue[i], vn in onetoone) for i, vn in enumerate(varnums)]
        mapinputs(trflist, mapping)  #initialize mappings if input mapping given
        todo = zip(varnums, trflist)

        for i, case in enumerate(ds.cases):
            for vnum, t in todo:
                ds.cases[i, vnum] = t.trf(case[vnum])
                
        # remove now irrelevant value labels and missing value codes
        for vn in varnums:
            allvariables[vn].valueLabels = {}
            allvariables[vn].missingValues = (0, None, None, None)

        # rename variables if requested
        # first find a number that guarantees no name conflicts.
        if nameroot:
            basenum = 0
            pat = re.compile(r"%s(\d+)$" % nameroot, re.IGNORECASE)
            for v in allvariables:
                try:
                    vnum = re.match(pat, v.name).group(1)
                    basenum = max(basenum, int(vnum))
                except:
                    pass
            basenum += 1   
            if namemapping:
                f = codecs.open(namemapping, "w", encoding="utf_8_sig")
            for vn in varnums:
                newname = nameroot + str(basenum)
                if len(newname) > 64:
                    raise ValueError("A replacement variable name is too long: %s" % newname)
                if namemapping:
                    f.write("%s = %s%s" % (allvariables[vn].name, newname, lineend))
                allvariables[vn].name = newname
                basenum += 1
            if namemapping:
                f.close()
                print "Variable name mappings written to file: %s" % namemapping
        ds.close()
        
        # write file of value mappings for each mapped variable in csv format
        if valuemapping:
            #f = codecs.open(valuemapping, "w", encoding="utf_8_sig")
            #csvout = csv.writer(f)
            f = file(valuemapping, "w")
            csvout = UnicodeWriter(f)
            for t in trflist:
                t.write(csvout)
            f.close()
            print "Value mappings written to file: %s" % valuemapping

def mapinputs(trflist, mapping):
    """Initialize mappings from file if given and method is Random
    
    trflist is the list of transformation objects
    mapping is the filespec for a previously written value mapping file
    Any previously mapped variables (method != transform) have their
    mapping table initialized to the previous mapping
    """
    
    if mapping is None:
        return
    f = file(mapping)
    fin = UnicodeReader(f)
    anonvars = dict([(t.vname, i) for i, t in enumerate(trflist)])  #mapped vars and Tvar index
    mappedvars = []
    try:
        row = fin.next()
        while True:
            if len(row) != 1:
                raise ValueError("Invalid format for mapping file")
            index = anonvars.get(row[0], -1)  # index of Tvar object
            t = index >= 0 and trflist[index] or None
            if t:
                mappedvars.append(t.vname)
            row = fin.next()
            maxseqvalue = -1
            while len(row) > 1:
                if t:
                    # for numeric variables, empty string must be mapped to None,
                    # the output value (row[0]) mapped to int, and the input value to float
                    # csv writes None values as empty strings :-(
                    if t.vtype == 0:   # numeric
                        if row[0] in ["", None]: 
                            row[0] = None
                        else:
                            row[0] = int(row[0])
                        if row[2] in ["", "None"]: 
                            row[2] = None
                        else:
                            row[2] = float(row[2])
                        maxseqvalue = max(maxseqvalue, row[0])  # ok with None input
                    else:
                        maxseqvalue = max(maxseqvalue, int(re.search(trailingdigits,row[0]).group(0)))
                    t.table[row[2]] = row[0]
                    if t.onetoone:
                        t.valueset.add(row[0])
                    t.seq = maxseqvalue
                row = fin.next()

    except StopIteration:
        print "Mappings initialized from file: %s\nVariables:\n" % mapping + "\n".join(mappedvars)
        
        
class Tvar(object):
    """Transform a variable according to specified method"""

    def __init__(self, v, svalueroot, method, offset, scale, maxrvalue, onetoone):
        attributesFromDict(locals())
        self.vtype = v.type
        self.vname = v.name
        if self.vtype > 0 and method == "transform":
            print """Transform method cannot be used with string variables.  
        Substituting method Sequential for variable %s""" % self.vname
            self.method = "sequential"
        if method == 'transform' and (offset is None or scale is None):
            raise ValueError("TRANSFORM method requires OFFSET and SCALE to be specified.")
        if method == "random" and maxrvalue <= 0:
            raise ValueError("The maximum value for the random method must be positive.")
        self.rootlen = len(svalueroot)
        self.table = {}
        self.seq = -1
        self.available = v.type - self.rootlen  # char available to random for strings
        # if no room for at least 1 digit, eliminate the prefix
        if self.available < 1:
            self.svalueroot = ""
            self.available = self.vtype
        if self.vtype > 0:
            self.maxrvalue = min(maxrvalue, 10 ** min(self.available, 20) - 1)
        if onetoone:
            self.valueset = set()
            self.directionfuncs = [self.up, self.down]


    def sequential(self, value):
        """Transform a value according to sequence"""
        if value in self.table:
            return self.table[value]
        self.seq += 1
        if self.vtype == 0:
            self.table[value] = self.seq
            return self.seq
        else:
            sseq = str(self.seq)
            newvalue = self.svalueroot + sseq
            if len(newvalue) > self.vtype:
                newvalue = newvalue[-self.vtype:]
            self.table[value] = newvalue
            return newvalue
    
    def transform(self, value):
        """Transform the value according to linear transform"""
        
        if value is None:
            return None
        return value * self.scale + self.offset
    
    def random(self, value):
        """Transform the value into a random integer"""
        
        if value in self.table:
            return self.table[value]
        rn = random.randint(0, min(self.maxrvalue, 0xffffffffffffff))
        if self.vtype == 0:
            ###rn = float(rn)
            if self.onetoone:
                rn = self.ensuredistinct(rn)
            self.table[value] = rn
            return rn
        # string variable
        newvalue = self.svalueroot + str(rn)
        newvalue = newvalue[-self.vtype:]
        if self.onetoone:
            newvalue = self.ensuredistinct(newvalue, re.search(trailingdigits, newvalue).group(0))
        self.table[value] = newvalue
        return newvalue
    
    def ensuredistinct(self, rn, trailingdigits=None):
        """Return a unique value or fail
        trailing digits is expected to be supplied for string values only"""
        
        if not rn in self.valueset:
            self.valueset.add(rn)
            return rn
        # search sequentially up and down to find next available value
        # direction to search first is random to keep the value distribution reasonably uniform
        random.shuffle(self.directionfuncs)
        res = self.directionfuncs[0](rn, trailingdigits)
        if res is None:
            res = self.directionfuncs[1](rn, trailingdigits)
        if res is None:
            raise ValueError("Cannot find unique value for variable: %s" % self.vname)
        return res

    def up(self, rn, trailingdigits):
        if trailingdigits is None:
            for i in xrange(rn + 1, self.maxrvalue+1):
                if not i in self.valueset:
                    self.valueset.add(i)
                    return i
            return None
        else:
            rnn = int(trailingdigits)
            prefixlen = len(rn) - len(trailingdigits)
            root = rn[:prefixlen]
            for i in xrange(rnn+1, self.maxrvalue+1):
                trialvalue = (root + str(i))[-self.vtype:]
                if not trialvalue in self.valueset:
                    self.valueset.add(trialvalue)
                    return trialvalue
            return None
    
    def down(self, rn, trailingdigits):
        if trailingdigits is None:
            for i in xrange(rn-1, -1,-1):
                if not i in self.valueset:
                    self.valueset.add(i)
                    return i
            return None
        else:
            rnn = int(trailingdigits)
            prefixlen = len(rn) - len(trailingdigits)
            root = rn[:prefixlen]
            for i in xrange(rnn-1, -1, -1):
                trialvalue = (root + str(i))[-self.vtype:]
                if not trialvalue in self.valueset:
                    self.valueset.add(trialvalue)
                    return trialvalue
            return None

    def trf(self, value):
        """transform a value for variable and return it
        value is the case value to transform
        """
        return getattr(Tvar, self.method)(self, value)
    
    def write(self, f):
        """Write value mapping to file f in csv format
        
        Header record has just the unmapped variable name
        Values are written as mapped value = input value
        Table is sorted by the mapped value for eas of lookup, but values
        are sorted as strings, so the order is not always the natural one for numbers.
        No values are written for method = transform, since no table is created.
        """
        #f.write("**Variable: %s%s" % (self.vname, lineend))
        f.writerow([self.vname])
        for k, v in sorted(self.table.iteritems(), key=itemgetter(1)):
            #f.write("%s\t=%s%s" %(v, k, lineend))
            f.writerow([unicode(v), "=", unicode(k)])
            
            
class UnicodeWriter:
    """
    A CSV writer which will write rows to CSV file "f",
    which is encoded in the given encoding.
    """

    def __init__(self, f, dialect=csv.excel, encoding="utf-8", **kwds):
        # Redirect output to a queue
        self.queue = cStringIO.StringIO()
        self.writer = csv.writer(self.queue, dialect=dialect, **kwds)
        self.stream = f
        self.encoder = codecs.getincrementalencoder(encoding)()

    def writerow(self, row):
        self.writer.writerow([s.encode("utf-8") for s in row])
        # Fetch UTF-8 output from the queue ...
        data = self.queue.getvalue()
        data = data.decode("utf-8")
        # ... and reencode it into the target encoding
        data = self.encoder.encode(data)
        # write to the target stream
        self.stream.write(data)
        # empty queue
        self.queue.truncate(0)

class UTF8Recoder:
    """
    Iterator that reads an encoded stream and reencodes the input to UTF-8
    """
    def __init__(self, f, encoding):
        self.reader = codecs.getreader(encoding)(f)

    def __iter__(self):
        return self

    def next(self):
        return self.reader.next().encode("utf-8")

class UnicodeReader:
    """
    A CSV reader which will iterate over lines in the CSV file "f",
    which is encoded in the given encoding.
    """

    def __init__(self, f, dialect=csv.excel, encoding="utf-8", **kwds):
        f = UTF8Recoder(f, encoding)
        self.reader = csv.reader(f, dialect=dialect, **kwds)

    def next(self):
        row = self.reader.next()
        return [unicode(s, "utf-8") for s in row]

    def __iter__(self):
        return self


    
def Run(args):
    """Execute the SPSSINC ANON extension command"""

    args = args[args.keys()[0]]

    oobj = Syntax([
        Template("VARIABLES", subc="",  ktype="existingvarlist", var="varnames", islist=True),
        Template("SVALUEROOT", subc="OPTIONS", ktype="literal", var="svalueroot"),
        Template("NAMEROOT", subc="OPTIONS", ktype="varname", var="nameroot"),
        Template("METHOD", subc="OPTIONS", ktype="str", var="method", 
            vallist=['random', 'sequential', 'transform']),
        Template("SEED", subc="OPTIONS", ktype="float", var="seed"),
        Template("OFFSET", subc="OPTIONS", ktype="float", var="offset"),
        Template("SCALE", subc="OPTIONS", ktype="float", var="scale"),
        Template("MAXRVALUE", subc="OPTIONS", ktype="int", var="maxrvalue", islist=True),
        Template("ONETOONE", subc="OPTIONS", ktype="existingvarlist", var="onetoone", islist=True),
        Template("MAPPING", subc="OPTIONS", ktype="literal", var="mapping"),
        Template("NAMEMAPPING", subc="SAVE", ktype="literal", var="namemapping"),
        Template("VALUEMAPPING", subc="SAVE", ktype="literal", var="valuemapping"),
        Template("IGNORETHIS", subc="SAVE", ktype="bool", var="ignorethis"),
        Template("HELP", subc="", ktype="bool")])
    
    # A HELP subcommand overrides all else
    if args.has_key("HELP"):
        #print helptext
        helper()
    else:
        processcmd(oobj, args, anon, vardict=spssaux.VariableDict())
        
        
def attributesFromDict(d):
    """build self attributes from a dictionary d."""

    # based on Python Cookbook, 2nd edition 6.18

    self = d.pop('self')
    for name, value in d.iteritems():
        setattr(self, name, value)
        
def helper():
    """open html help in default browser window
    
    The location is computed from the current module name"""
    
    import webbrowser, os.path
    
    path = os.path.splitext(__file__)[0]
    helpspec = "file://" + path + os.path.sep + \
         "markdown.html"
    
    # webbrowser.open seems not to work well
    browser = webbrowser.get()
    if not browser.open_new(helpspec):
        print("Help file not found:" + helpspec)
try:    #override
    from extension import helper
except:
    pass